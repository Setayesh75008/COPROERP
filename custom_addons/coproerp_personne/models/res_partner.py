from odoo import models, fields


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ==========================
    # Rôles CoproERP
    # ==========================

    role_coproprietaire = fields.Boolean(
        string="Copropriétaire"
    )

    role_locataire = fields.Boolean(
        string="Locataire"
    )

    role_fournisseur = fields.Boolean(
        string="Fournisseur"
    )

    role_conseil_syndical = fields.Boolean(
        string="Conseil syndical"
    )

    role_gardien = fields.Boolean(
        string="Gardien"
    )

    # ==========================
    # Lots CoproERP
    # ==========================

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