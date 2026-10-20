from odoo import models


class BudgetAnnuel(models.Model):
    _inherit = "coproerp.budget.annuel"

    def action_cloture(self):
        """Ouvre la clôture de l'exercice (et ses annexes), en la créant au besoin."""
        self.ensure_one()
        Cloture = self.env["coproerp.cloture"]
        cloture = Cloture.search([("budget_id", "=", self.id)], limit=1)
        if not cloture:
            cloture = Cloture.create({"budget_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": cloture.name,
            "res_model": "coproerp.cloture",
            "res_id": cloture.id,
            "view_mode": "form",
        }
