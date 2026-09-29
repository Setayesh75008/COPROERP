from odoo import models, fields


class LotNavigation(models.Model):
    _inherit = "coproerp.lot"

    repartition_line_ids = fields.One2many(
        "coproerp.repartition.lot",
        "lot_id",
        string="Répartitions des tantièmes",
    )