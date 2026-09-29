from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    coproerp_appel_id = fields.Many2one(
        "coproerp.appel.charge",
        string="Appel de fonds",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    coproerp_reglement_id = fields.Many2one(
        "coproerp.reglement",
        string="Règlement copropriétaire",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
