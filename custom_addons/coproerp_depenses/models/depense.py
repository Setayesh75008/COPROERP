from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

COMPTE_FOURNISSEURS = "401000"

CHAMPS_VERROUILLES = {
    "copropriete_id", "fournisseur_id", "reference_fournisseur", "date_facture",
    "date_echeance", "travaux_id", "ligne_ids",
}


class Depense(models.Model):
    """Facture d'un fournisseur de la copropriété.

    Saisie TTC (le syndicat ne récupère pas la TVA). Chaque ligne porte une
    nature de dépense (compte 6xx) et une clé de répartition : c'est cette clé
    qui servira à répartir la dépense entre les copropriétaires à la
    régularisation des charges.
    """

    _name = "coproerp.depense"
    _description = "Facture fournisseur (dépense de la copropriété)"
    _inherit = ["mail.thread"]
    _order = "date_facture desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, tracking=True
    )
    fournisseur_id = fields.Many2one(
        "res.partner", string="Fournisseur", required=True, index=True, tracking=True
    )
    reference_fournisseur = fields.Char(string="N° de facture du fournisseur", tracking=True)
    date_facture = fields.Date(
        string="Date de la facture", required=True, default=fields.Date.context_today, tracking=True
    )
    date_echeance = fields.Date(string="Date d'échéance", tracking=True)
    budget_id = fields.Many2one(
        "coproerp.budget.annuel",
        string="Exercice (budget)",
        compute="_compute_budget_id",
        store=True,
        index=True,
    )
    travaux_id = fields.Many2one(
        "coproerp.travaux",
        string="Opération de travaux",
        domain="[('copropriete_id', '=', copropriete_id)]",
        tracking=True,
        help="À renseigner pour les travaux décidés par l'assemblée (art. 14-2) : "
        "la dépense est alors suivie hors budget.",
    )
    ligne_ids = fields.One2many("coproerp.depense.ligne", "depense_id", string="Ventilation", copy=True)
    montant_total = fields.Float(
        string="Montant TTC", compute="_compute_montant_total", store=True, digits=(16, 2), tracking=True
    )
    etat = fields.Selection(
        [("brouillon", "Brouillon"), ("validee", "Comptabilisée"), ("annulee", "Annulée")],
        string="État",
        default="brouillon",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
    )
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)
    move_annulation_id = fields.Many2one("account.move", string="Écriture d'annulation", readonly=True, copy=False)
    montant_restant = fields.Float(
        string="Reste à payer", compute="_compute_montant_restant", digits=(16, 2)
    )
    est_payee = fields.Boolean(string="Payée", readonly=True, copy=False, index=True)
    paiement_ids = fields.One2many("coproerp.depense.paiement", "depense_id", string="Paiements")
    justificatif = fields.Binary(string="Facture (PDF)", attachment=True, copy=False)
    justificatif_nom = fields.Char(string="Nom du fichier", copy=False)
    note = fields.Text(string="Note interne")

    # ------------------------------------------------------------------
    @api.depends("copropriete_id", "date_facture")
    def _compute_budget_id(self):
        Budget = self.env["coproerp.budget.annuel"]
        for depense in self:
            budget = Budget
            if depense.copropriete_id and depense.date_facture:
                budget = Budget.search([
                    ("copropriete_id", "=", depense.copropriete_id.id),
                    ("date_debut", "<=", depense.date_facture),
                    ("date_fin", ">=", depense.date_facture),
                ], order="date_debut desc", limit=1)
            depense.budget_id = budget

    @api.depends("ligne_ids.montant")
    def _compute_montant_total(self):
        for depense in self:
            depense.montant_total = sum(depense.ligne_ids.mapped("montant"))

    @api.depends("etat", "montant_total", "move_id.line_ids.amount_residual")
    def _compute_montant_restant(self):
        for depense in self:
            if depense.etat == "annulee":
                depense.montant_restant = 0.0
            elif depense.etat == "brouillon" or not depense.move_id:
                depense.montant_restant = depense.montant_total
            else:
                lignes = depense.move_id.sudo().line_ids.filtered(
                    lambda l: l.account_id.account_type == "liability_payable"
                )
                depense.montant_restant = -sum(lignes.mapped("amount_residual"))

    @api.constrains("date_facture")
    def _check_date_facture(self):
        for depense in self:
            if depense.date_facture and depense.date_facture > fields.Date.context_today(depense):
                raise ValidationError("La date de la facture ne peut pas être dans le futur.")

    @api.constrains("copropriete_id", "fournisseur_id", "reference_fournisseur", "etat")
    def _check_doublon(self):
        for depense in self.filtered(lambda d: d.reference_fournisseur and d.etat != "annulee"):
            doublon = self.search_count([
                ("id", "!=", depense.id),
                ("copropriete_id", "=", depense.copropriete_id.id),
                ("fournisseur_id", "=", depense.fournisseur_id.id),
                ("reference_fournisseur", "=ilike", depense.reference_fournisseur.strip()),
                ("etat", "!=", "annulee"),
            ])
            if doublon:
                raise ValidationError(
                    "La facture n° %s de %s est déjà enregistrée pour cette copropriété."
                    % (depense.reference_fournisseur, depense.fournisseur_id.name)
                )

    @api.constrains("travaux_id", "ligne_ids")
    def _check_travaux(self):
        for depense in self:
            if not depense.travaux_id and depense.ligne_ids.filtered("nature_id.travaux"):
                raise ValidationError(
                    "Une dépense de « travaux décidés par l'assemblée » doit être rattachée "
                    "à une opération de travaux."
                )

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.depense") or "/"
        return super().create(vals_list)

    def write(self, vals):
        if CHAMPS_VERROUILLES & set(vals) and self.filtered(lambda d: d.etat != "brouillon"):
            raise UserError(
                "Cette facture est comptabilisée : elle ne peut plus être modifiée. "
                "Annulez-la puis saisissez-la de nouveau."
            )
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda d: d.etat != "brouillon"):
            raise UserError("Une facture comptabilisée ne peut pas être supprimée : annulez-la.")
        return super().unlink()

    # ------------------------------------------------------------------
    def action_valider(self):
        for depense in self.filtered(lambda d: d.etat == "brouillon"):
            company = depense.copropriete_id._verifier_dossier()
            depense = depense.with_company(company)
            copro = depense.copropriete_id
            arrondi = company.currency_id.round
            if not depense.ligne_ids:
                raise UserError("Ventilez la facture : ajoutez au moins une ligne.")
            commandes = []
            total = 0.0
            for ligne in depense.ligne_ids:
                montant = arrondi(ligne.montant)
                if montant <= 0:
                    raise UserError("Chaque ligne doit avoir un montant positif.")
                total += montant
                commandes.append(Command.create({
                    "account_id": copro._compte(ligne.nature_id.code).id,
                    "partner_id": depense.fournisseur_id.id,
                    "name": ligne.designation or ligne.nature_id.name,
                    "debit": montant,
                    "credit": 0.0,
                    "coproerp_repartition_id": ligne.repartition_id.id,
                    "coproerp_hors_budget": bool(ligne.nature_id.travaux or depense.travaux_id),
                    "coproerp_travaux_id": depense.travaux_id.id or False,
                }))
            total = arrondi(total)
            libelle = "Facture %s %s" % (depense.reference_fournisseur or depense.name, depense.fournisseur_id.name)
            commandes.append(Command.create({
                "account_id": copro._compte(COMPTE_FOURNISSEURS).id,
                "partner_id": depense.fournisseur_id.id,
                "name": libelle,
                "debit": 0.0,
                "credit": total,
                "date_maturity": depense.date_echeance or depense.date_facture,
            }))
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry",
                "journal_id": copro._journal("achats").id,
                "date": depense.date_facture,
                "ref": "%s %s" % (depense.name, libelle),
                "coproerp_depense_id": depense.id,
                "line_ids": commandes,
            })
            move.action_post()
            depense.write({"move_id": move.id, "etat": "validee"})
        return True

    def action_annuler(self):
        for depense in self.filtered(lambda d: d.etat == "validee"):
            if depense.paiement_ids.filtered(lambda p: p.etat == "valide"):
                raise UserError(
                    "Cette facture a des paiements : annulez d'abord les paiements."
                )
            depense = depense.with_company(depense.copropriete_id._verifier_dossier())
            date = max(fields.Date.context_today(self), depense.move_id.date)
            annulation = depense.move_id._reverse_moves(
                [{"date": date, "ref": "Annulation %s" % (depense.move_id.ref or "")}], cancel=True
            )
            depense.write({"etat": "annulee", "move_annulation_id": annulation.id, "est_payee": False})
        return True

    def action_enregistrer_paiement(self):
        self.ensure_one()
        if self.etat != "validee":
            raise UserError("Comptabilisez d'abord la facture.")
        vue = self.env.ref("coproerp_depenses.view_depense_paiement_form_dialog")
        return {
            "type": "ir.actions.act_window",
            "name": "Paiement de la facture %s" % self.name,
            "res_model": "coproerp.depense.paiement",
            "view_mode": "form",
            "views": [(vue.id, "form")],
            "target": "new",
            "context": {
                "default_depense_id": self.id,
                "default_montant": self.montant_restant,
            },
        }

    def _maj_statut_paiement(self):
        self.invalidate_recordset(["montant_restant"])
        for depense in self:
            payee = depense.etat == "validee" and float_is_zero(depense.montant_restant, precision_digits=2)
            if depense.est_payee != payee:
                depense.est_payee = payee


class DepenseLigne(models.Model):
    _name = "coproerp.depense.ligne"
    _description = "Ligne de ventilation d'une facture fournisseur"
    _order = "sequence, id"

    depense_id = fields.Many2one("coproerp.depense", required=True, ondelete="cascade", index=True)
    copropriete_id = fields.Many2one(related="depense_id.copropriete_id", store=True)
    sequence = fields.Integer(default=10)
    nature_id = fields.Many2one(
        "coproerp.nature.depense", string="Nature de la dépense", required=True, ondelete="restrict"
    )
    designation = fields.Char(string="Libellé")
    repartition_id = fields.Many2one(
        "coproerp.repartition",
        string="Clé de répartition",
        required=True,
        ondelete="restrict",
        domain="[('copropriete_id', '=', copropriete_id)]",
    )
    montant = fields.Float(string="Montant TTC", digits=(16, 2), required=True)

    @api.constrains("repartition_id", "depense_id")
    def _check_cle(self):
        for ligne in self:
            if ligne.repartition_id.copropriete_id != ligne.depense_id.copropriete_id:
                raise ValidationError("La clé de répartition doit appartenir à la copropriété de la facture.")

    def _verifier_modifiable(self):
        if self.depense_id.filtered(lambda d: d.etat != "brouillon"):
            raise UserError("Cette facture est comptabilisée : sa ventilation ne peut plus être modifiée.")

    @api.model_create_multi
    def create(self, vals_list):
        lignes = super().create(vals_list)
        lignes._verifier_modifiable()
        return lignes

    def write(self, vals):
        self._verifier_modifiable()
        return super().write(vals)

    def unlink(self):
        self._verifier_modifiable()
        return super().unlink()
