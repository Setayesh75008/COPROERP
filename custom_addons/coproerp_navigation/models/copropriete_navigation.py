from odoo import models, fields


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    batiment_ids = fields.One2many(
        "coproerp.batiment",
        "copropriete_id",
        string="Bâtiments",
    )

    repartition_ids = fields.One2many(
        "coproerp.repartition",
        "copropriete_id",
        string="Clés de répartition",
    )