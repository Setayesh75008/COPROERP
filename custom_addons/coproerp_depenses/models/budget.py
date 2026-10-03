from odoo import fields, models


class BudgetLigne(models.Model):
    _inherit = "coproerp.budget.ligne"

    montant_realise = fields.Float(
        string="Réalisé", compute="_compute_realise", digits=(16, 2),
        help="Dépenses comptabilisées sur l'exercice pour cette clé "
        "(hors travaux décidés par l'assemblée).",
    )
    ecart_realise = fields.Float(
        string="Écart (budget − réalisé)", compute="_compute_realise", digits=(16, 2)
    )

    def _compute_realise(self):
        MoveLine = self.env["account.move.line"].sudo()
        for ligne in self:
            budget = ligne.budget_id
            company = budget.copropriete_id.company_id
            realise = 0.0
            if company and ligne.repartition_id and budget.date_debut and budget.date_fin:
                lignes = MoveLine.search([
                    ("company_id", "=", company.id),
                    ("parent_state", "=", "posted"),
                    ("account_id.account_type", "in", ("expense", "expense_other")),
                    ("coproerp_repartition_id", "=", ligne.repartition_id.id),
                    ("coproerp_hors_budget", "=", False),
                    ("date", ">=", budget.date_debut),
                    ("date", "<=", budget.date_fin),
                ])
                realise = round(sum(lignes.mapped("balance")), 2)
            ligne.montant_realise = realise
            ligne.ecart_realise = round(ligne.montant_annuel - realise, 2)


class BudgetAnnuel(models.Model):
    _inherit = "coproerp.budget.annuel"

    depense_ids = fields.One2many("coproerp.depense", "budget_id", string="Factures de l'exercice")
    total_realise = fields.Float(string="Total réalisé", compute="_compute_total_realise", digits=(16, 2))

    def _compute_total_realise(self):
        for budget in self:
            budget.total_realise = round(sum(budget.ligne_ids.mapped("montant_realise")), 2)

    def action_voir_depenses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Factures – %s" % (self.display_name or ""),
            "res_model": "coproerp.depense",
            "view_mode": "list,form",
            "domain": [("budget_id", "=", self.id)],
            "context": {"default_copropriete_id": self.copropriete_id.id},
        }
