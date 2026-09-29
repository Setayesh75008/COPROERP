from odoo import fields, models


class MiseEnReserve(models.TransientModel):
    _name = "coproerp.mise.en.reserve"
    _description = "Mise en réserve du fonds de travaux (clôture)"

    copropriete_id = fields.Many2one("coproerp.copropriete", required=True, readonly=True)
    date_cloture = fields.Date(
        string="Date de clôture de l'exercice",
        required=True,
        help="Le solde du compte 705 à cette date est viré au compte 105, "
        "copropriétaire par copropriétaire.",
    )

    def action_valider(self):
        self.ensure_one()
        move = self.copropriete_id._mettre_en_reserve_fonds_travaux(self.date_cloture)
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
        }
