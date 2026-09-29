from odoo import models, fields


class ResPartnerNavigation(models.Model):
    _inherit = "res.partner"

    # ==========================================
    # Navigation vers les droits
    # ==========================================

    droit_ids = fields.One2many(
        "coproerp.droit",
        "personne_id",
        string="Droits",
    )

    # ==========================================
    # Navigation vers les lots
    # ==========================================

    lot_proprietaire_ids = fields.Many2many(
        "coproerp.lot",
        "coproerp_lot_proprietaire_rel",
        "partner_id",
        "lot_id",
        string="Lots propriétaires",
    )

    lot_occupant_ids = fields.Many2many(
        "coproerp.lot",
        "coproerp_lot_occupant_rel",
        "partner_id",
        "lot_id",
        string="Lots occupants",
    )