from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from .depense import COMPTE_FOURNISSEURS


class DepensePaiement(models.Model):
    """Paiement d'une facture fournisseur.

    À la validation : écriture au journal de banque (débit 401 / crédit 512),
    lettrée avec la facture. Un paiement validé ne se modifie pas : on
    l'annule par contre-passation.
    """

    _name = "coproerp.depense.paiement"
    _description = "Paiement d'une facture fournisseur"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    depense_id = fields.Many2one(
        "coproerp.depense",
        string="Facture",
        required=True,
        index=True,
        domain="[('etat', '=', 'validee'), ('est_payee', '=', False)]",
        tracking=True,
    )
    copropriete_id = fields.Many2one(related="depense_id.copropriete_id", store=True, string="Copropriété")
    fournisseur_id = fields.Many2one(related="depense_id.fournisseur_id", store=True, string="Fournisseur")
    date = fields.Date(
        string="Date du paiement", required=True, default=fields.Date.context_today, tracking=True
    )
    montant = fields.Float(string="Montant", digits=(16, 2), required=True, tracking=True)
    mode = fields.Selection(
        [
            ("virement", "Virement"),
            ("prelevement", "Prélèvement"),
            ("cheque", "Chèque"),
            ("autre", "Autre"),
        ],
        string="Mode de paiement",
        required=True,
        default="virement",
        tracking=True,
    )
    reference = fields.Char(string="Référence (n° de chèque, libellé du virement…)", tracking=True)
    etat = fields.Selection(
        [("brouillon", "Brouillon"), ("valide", "Réalisé"), ("annule", "Annulé")],
        string="État",
        default="brouillon",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)
    move_annulation_id = fields.Many2one("account.move", string="Écriture d'annulation", readonly=True, copy=False)

    @api.constrains("montant")
    def _check_montant(self):
        for paiement in self:
            if paiement.montant <= 0:
                raise ValidationError("Le montant d'un paiement doit être positif.")

    @api.constrains("date")
    def _check_date(self):
        for paiement in self:
            if paiement.date and paiement.date > fields.Date.context_today(paiement):
                raise ValidationError("La date d'un paiement ne peut pas être dans le futur.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.depense.paiement") or "/"
        return super().create(vals_list)

    def write(self, vals):
        champs = {"depense_id", "date", "montant", "mode"}
        if champs & set(vals) and self.filtered(lambda p: p.etat != "brouillon"):
            raise UserError("Un paiement validé ne peut plus être modifié : annulez-le puis ressaisissez-le.")
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda p: p.etat != "brouillon"):
            raise UserError("Un paiement validé ne peut pas être supprimé : annulez-le.")
        return super().unlink()

    # ------------------------------------------------------------------
    def action_valider(self):
        for paiement in self.filtered(lambda p: p.etat == "brouillon"):
            depense = paiement.depense_id
            if depense.etat != "validee":
                raise UserError("La facture %s n'est pas comptabilisée." % depense.name)
            company = depense.copropriete_id._verifier_dossier()
            paiement = paiement.with_company(company)
            depense = paiement.depense_id
            copro = depense.copropriete_id
            arrondi = company.currency_id.round
            montant = arrondi(paiement.montant)
            depense.invalidate_recordset(["montant_restant"])
            if float_compare(montant, depense.montant_restant, precision_digits=2) > 0:
                raise UserError(
                    "Le paiement (%.2f €) dépasse le reste à payer de la facture (%.2f €)."
                    % (montant, depense.montant_restant)
                )
            journal = copro._journal("banque")
            if not journal.default_account_id:
                raise UserError("Le journal de banque n'a pas de compte (512).")
            compte_401 = copro._compte(COMPTE_FOURNISSEURS)
            libelle = "Paiement %s %s" % (depense.reference_fournisseur or depense.name, depense.fournisseur_id.name)
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry",
                "journal_id": journal.id,
                "date": paiement.date,
                "ref": "%s %s" % (paiement.name, libelle),
                "coproerp_paiement_id": paiement.id,
                "line_ids": [
                    Command.create({
                        "account_id": compte_401.id,
                        "partner_id": depense.fournisseur_id.id,
                        "name": libelle,
                        "debit": montant,
                        "credit": 0.0,
                    }),
                    Command.create({
                        "account_id": journal.default_account_id.id,
                        "partner_id": depense.fournisseur_id.id,
                        "name": libelle,
                        "debit": 0.0,
                        "credit": montant,
                    }),
                ],
            })
            move.action_post()
            a_lettrer = (move.line_ids | depense.move_id.line_ids).filtered(
                lambda l: l.account_id == compte_401 and not l.reconciled
            )
            a_lettrer.reconcile()
            paiement.write({"move_id": move.id, "etat": "valide"})
            depense._maj_statut_paiement()
        return True

    def action_annuler(self):
        for paiement in self.filtered(lambda p: p.etat == "valide"):
            company = paiement.copropriete_id._verifier_dossier()
            paiement = paiement.with_company(company)
            date = max(fields.Date.context_today(self), paiement.move_id.date)
            annulation = paiement.move_id._reverse_moves(
                [{"date": date, "ref": "Annulation %s" % (paiement.move_id.ref or "")}], cancel=True
            )
            paiement.write({"etat": "annule", "move_annulation_id": annulation.id})
            paiement.depense_id._maj_statut_paiement()
        return True
