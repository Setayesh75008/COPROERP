from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

COMPTE_FOURNISSEURS = "401000"


class PaiementGroupe(models.Model):
    """Paiement de plusieurs factures d'un même fournisseur en une fois (avoirs déduits)."""

    _name = "coproerp.paiement.groupe"
    _description = "Paiement groupé de factures fournisseurs"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    copropriete_id = fields.Many2one("coproerp.copropriete", string="Copropriété", required=True, index=True)
    fournisseur_id = fields.Many2one("res.partner", string="Fournisseur", required=True)
    date = fields.Date(string="Date du paiement", required=True, default=fields.Date.context_today)
    mode = fields.Selection(
        [("virement", "Virement"), ("prelevement", "Prélèvement"), ("cheque", "Chèque"), ("autre", "Autre")],
        string="Mode de paiement", required=True, default="virement")
    reference = fields.Char(string="Référence (n° de chèque, libellé du virement…)")
    depense_ids = fields.Many2many(
        "coproerp.depense", "coproerp_paiement_groupe_depense_rel", "groupe_id", "depense_id",
        string="Factures et avoirs",
        domain="[('copropriete_id', '=', copropriete_id), ('fournisseur_id', '=', fournisseur_id), "
               "('etat', '=', 'validee'), ('est_payee', '=', False)]")
    montant = fields.Float(string="Montant à payer", compute="_compute_montant", digits=(16, 2))
    etat = fields.Selection(
        [("brouillon", "Brouillon"), ("valide", "Réalisé"), ("annule", "Annulé")],
        string="État", default="brouillon", required=True, readonly=True, copy=False, tracking=True)
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)
    move_annulation_id = fields.Many2one("account.move", string="Écriture d'annulation", readonly=True, copy=False)

    @api.depends("depense_ids.montant_restant", "etat")
    def _compute_montant(self):
        for groupe in self:
            groupe.montant = round(sum(groupe.depense_ids.mapped("montant_restant")), 2)

    @api.constrains("date")
    def _check_date(self):
        for groupe in self:
            if groupe.date > fields.Date.context_today(groupe):
                raise ValidationError("La date d'un paiement ne peut pas être dans le futur.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.paiement.groupe") or "/"
        return super().create(vals_list)

    def action_valider(self):
        for groupe in self.filtered(lambda g: g.etat == "brouillon"):
            if not groupe.depense_ids:
                raise UserError("Sélectionnez les factures à payer.")
            if groupe.depense_ids.filtered(lambda d: d.fournisseur_id != groupe.fournisseur_id or d.etat != "validee"
                                           or d.est_payee):
                raise UserError("Les pièces doivent être des factures ou avoirs comptabilisés, non soldés, du même "
                                "fournisseur.")
            montant = groupe.montant
            if montant < -0.005:
                raise UserError("Les avoirs dépassent les factures sélectionnées (%.2f €)." % montant)
            copro = groupe.copropriete_id
            company = copro._verifier_dossier()
            compte_401 = copro._compte(COMPTE_FOURNISSEURS)
            libelle = "Paiement groupé %s %s" % (groupe.reference or groupe.name, groupe.fournisseur_id.name)
            commandes = []
            for depense in groupe.depense_ids:
                reste = round(depense.montant_restant, 2)
                commandes.append(Command.create({
                    "account_id": compte_401.id, "partner_id": groupe.fournisseur_id.id,
                    "name": "%s – %s" % (libelle, depense.name),
                    "debit": reste if reste > 0 else 0.0, "credit": -reste if reste < 0 else 0.0,
                }))
            journal = copro._journal("banque") if montant > 0.005 else copro._journal("od")
            if montant > 0.005:
                commandes.append(Command.create({
                    "account_id": journal.default_account_id.id, "partner_id": groupe.fournisseur_id.id,
                    "name": libelle, "credit": round(montant, 2),
                }))
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry", "journal_id": journal.id, "date": groupe.date,
                "ref": "%s %s" % (groupe.name, libelle), "line_ids": commandes,
            })
            move.action_post()
            for depense in groupe.depense_ids:
                lignes = (move.line_ids | depense.move_id.line_ids).filtered(
                    lambda l: l.account_id == compte_401 and not l.reconciled
                    and (l.move_id == depense.move_id or (l.name or "").endswith(depense.name)))
                if len(lignes) > 1:
                    lignes.reconcile()
            groupe.depense_ids._maj_statut_paiement()
            groupe.write({"etat": "valide", "move_id": move.id})
        return True

    def action_annuler(self):
        for groupe in self.filtered(lambda g: g.etat == "valide"):
            company = groupe.copropriete_id._verifier_dossier()
            move = groupe.move_id.with_company(company)
            date = max(fields.Date.context_today(groupe), move.date)
            annulation = move._reverse_moves([{"date": date, "ref": "Annulation %s" % move.ref}], cancel=True)
            groupe.write({"etat": "annule", "move_annulation_id": annulation.id})
            groupe.depense_ids._maj_statut_paiement()
        return True
