from odoo import models
from odoo.exceptions import UserError


class BudgetAnnuel(models.Model):
    _inherit = "coproerp.budget.annuel"

    def action_regularisation(self):
        self.ensure_one()
        Regul = self.env["coproerp.regularisation"]
        regul = Regul.search([("budget_id", "=", self.id), ("etat", "!=", "annulee")], limit=1)
        if not regul:
            regul = Regul.create({"budget_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": regul.name,
            "res_model": "coproerp.regularisation",
            "res_id": regul.id,
            "view_mode": "form",
        }

    def _est_regularise(self):
        self.ensure_one()
        return bool(self.env["coproerp.regularisation"].search_count([
            ("budget_id", "=", self.id), ("etat", "=", "comptabilisee"),
        ]))


class Depense(models.Model):
    _inherit = "coproerp.depense"

    def action_valider(self):
        for depense in self:
            if depense.budget_id and depense.budget_id._est_regularise():
                raise UserError(
                    "Les charges de l'exercice %s sont déjà régularisées : une nouvelle facture "
                    "datée de cet exercice fausserait les décomptes. Annulez d'abord la "
                    "régularisation, ou datez la facture de l'exercice suivant."
                    % (depense.budget_id.exercice or "")
                )
        return super().action_valider()
