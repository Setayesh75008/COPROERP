from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    role_bailleur = fields.Boolean(string="Propriétaire bailleur (mandant)")
    role_garant = fields.Boolean(string="Garant (caution)")
    locatif_mandat_ids = fields.One2many("coproerp.locatif.mandat", "proprietaire_id", string="Mandats de gestion")
    locatif_bail_ids = fields.Many2many("coproerp.locatif.bail", "coproerp_locatif_bail_locataire_rel",
                                        "partner_id", "bail_id", string="Baux (locataire)")
