from odoo import models, fields


class BatimentNavigation(models.Model):
    _inherit = "coproerp.batiment"

    lot_ids = fields.One2many(
        "coproerp.lot",
        "batiment_id",
        string="Lots",
    )
    