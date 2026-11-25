from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    locatif_nature = fields.Selection(selection_add=[("sortie", "Sortie du locataire (dépôt de garantie)")],
                                      ondelete={"sortie": "set null"})
