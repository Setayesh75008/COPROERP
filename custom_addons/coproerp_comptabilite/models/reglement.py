from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError


class Reglement(models.Model):
    """Règlement reçu d'un copropriétaire.

    À la validation : écriture au journal de banque (débit 512 / crédit 450xxx),
    imputée sur les appels non soldés les plus anciens, puis lettrage.
    Un éventuel excédent reste au crédit du copropriétaire (compte budget) et
    sera imputé automatiquement sur ses prochains appels.
    """

    _name = "coproerp.reglement"
    _description = "Règlement d'un copropriétaire"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, tracking=True
    )
    personne_id = fields.Many2one(
        "res.partner", string="Copropriétaire", required=True, index=True, tracking=True
    )
    date = fields.Date(
        string="Date de réception", required=True, default=fields.Date.context_today, tracking=True
    )
    montant = fields.Float(string="Montant", digits=(16, 2), required=True, tracking=True)
    mode = fields.Selection(
        [
            ("virement", "Virement"),
            ("prelevement", "Prélèvement SEPA"),
            ("cheque", "Chèque"),
            ("especes", "Espèces"),
            ("autre", "Autre"),
        ],
        string="Mode de règlement",
        required=True,
        default="virement",
        tracking=True,
    )
    reference = fields.Char(string="Référence (libellé du virement, n° de chèque…)", tracking=True)
    etat = fields.Selection(
        [("brouillon", "Brouillon"), ("valide", "Validé"), ("annule", "Annulé")],
        string="État",
        default="brouillon",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)
    move_annulation_id = fields.Many2one("account.move", string="Écriture d'annulation", readonly=True, copy=False)
    motif_annulation = fields.Char(string="Motif d'annulation", readonly=True, copy=False)
    imputation = fields.Text(string="Imputation", readonly=True, copy=False)

    @api.constrains("montant")
    def _check_montant(self):
        for reglement in self:
            if reglement.montant <= 0:
                raise ValidationError("Le montant d'un règlement doit être positif.")

    @api.constrains("date")
    def _check_date(self):
        for reglement in self:
            if reglement.date and reglement.date > fields.Date.context_today(reglement):
                raise ValidationError(
                    "La date de réception d'un règlement ne peut pas être dans le futur."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.reglement") or "/"
        return super().create(vals_list)

    def write(self, vals):
        champs = {"copropriete_id", "personne_id", "date", "montant", "mode"}
        if champs & set(vals) and self.filtered(lambda r: r.etat != "brouillon"):
            raise UserError("Un règlement validé ne peut plus être modifié : annulez-le puis ressaisissez-le.")
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda r: r.etat != "brouillon"):
            raise UserError("Un règlement validé ne peut pas être supprimé : annulez-le.")
        return super().unlink()

    # ------------------------------------------------------------------
    def _lignes_a_solder(self):
        """Appels non soldés du copropriétaire, du plus ancien au plus récent."""
        self.ensure_one()
        copro = self.copropriete_id
        return self.env["account.move.line"].search([
            ("company_id", "=", copro.company_id.id),
            ("account_id", "in", copro._comptes_coproprietaires().ids),
            ("partner_id", "=", self.personne_id.id),
            ("parent_state", "=", "posted"),
            ("reconciled", "=", False),
            ("amount_residual", ">", 0),
        ], order="date_maturity, date, id")

    def action_valider(self):
        for reglement in self.filtered(lambda r: r.etat == "brouillon"):
            company = reglement.copropriete_id._verifier_dossier()
            # Société de la copropriété active, même si elle n'est pas cochée
            # dans le sélecteur : sinon la recherche des appels à solder
            # serait vide (règles multi-sociétés).
            reglement = reglement.with_company(company)
            copro = reglement.copropriete_id
            arrondi = company.currency_id.round
            journal = copro._journal("banque")
            if not journal.default_account_id:
                raise UserError("Le journal de banque n'a pas de compte (512).")
            libelle = "Règlement %s %s" % (
                dict(self._fields["mode"]._description_selection(self.env)).get(reglement.mode, ""),
                reglement.reference or "",
            )
            reste = arrondi(reglement.montant)
            imputations = []  # (ligne à solder, montant)
            for ligne in reglement._lignes_a_solder():
                if reste <= 0:
                    break
                part = arrondi(min(reste, ligne.amount_residual))
                imputations.append((ligne, part))
                reste = arrondi(reste - part)

            commandes = [Command.create({
                "account_id": journal.default_account_id.id,
                "partner_id": reglement.personne_id.id,
                "name": libelle.strip(),
                "debit": arrondi(reglement.montant),
                "credit": 0.0,
            })]
            for ligne, part in imputations:
                commandes.append(Command.create({
                    "account_id": ligne.account_id.id,
                    "partner_id": reglement.personne_id.id,
                    "name": "Votre règlement %s" % (reglement.reference or reglement.name),
                    "debit": 0.0,
                    "credit": part,
                }))
            if reste > 0:
                commandes.append(Command.create({
                    "account_id": copro._compte(copro.compte_copro_budget).id,
                    "partner_id": reglement.personne_id.id,
                    "name": "Votre règlement %s (versé d'avance)" % (reglement.reference or reglement.name),
                    "debit": 0.0,
                    "credit": reste,
                }))
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry",
                "journal_id": journal.id,
                "date": reglement.date,
                "ref": "%s %s" % (reglement.name, reglement.personne_id.name or ""),
                "coproerp_reglement_id": reglement.id,
                "line_ids": commandes,
            })
            move.action_post()

            # Lettrage : chaque ligne de crédit avec l'appel qu'elle solde
            disponibles = move.line_ids.filtered(lambda l: l.credit).sorted("id")
            texte = []
            for ligne, part in imputations:
                credit = disponibles.filtered(
                    lambda l: l.account_id == ligne.account_id
                    and not arrondi(l.credit - part)
                )[:1]
                disponibles -= credit
                (credit | ligne).reconcile()
                texte.append("%.2f € sur %s" % (part, ligne.move_id.ref or ligne.name))
            if reste > 0:
                texte.append("%.2f € au crédit du copropriétaire (versé d'avance)" % reste)
            reglement.write({"move_id": move.id, "etat": "valide", "imputation": "\n".join(texte)})
        return True

    def action_annuler(self):
        """Chèque impayé, erreur de saisie… : contre-passation de l'écriture."""
        for reglement in self.filtered(lambda r: r.etat == "valide"):
            reglement = reglement.with_company(reglement.copropriete_id._verifier_dossier())
            date = max(fields.Date.context_today(self), reglement.move_id.date)
            annulation = reglement.move_id._reverse_moves(
                [{"date": date, "ref": "Annulation %s" % (reglement.move_id.ref or "")}], cancel=True
            )
            reglement.write({
                "etat": "annule",
                "move_annulation_id": annulation.id,
                "motif_annulation": self.env.context.get("motif_annulation") or "Annulation",
            })
        return True
