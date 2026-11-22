from odoo import fields, models

NATURES = [
    ("honoraires", "Honoraires de gestion"),
    ("depense", "Facture payée pour le propriétaire"),
    ("reversement", "Virement au propriétaire"),
    ("honoraires_cabinet", "Virement des honoraires au cabinet"),
]


class AccountMove(models.Model):
    _inherit = "account.move"

    # Renseignée par le contexte « locatif_nature » au moment où l'écriture est créée ;
    # copiée sur l'écriture d'annulation pour que le compte rendu les classe ensemble.
    locatif_nature = fields.Selection(NATURES, string="Nature (gestion locative)", copy=True, readonly=True,
                                      default=lambda self: self.env.context.get("locatif_nature"))
