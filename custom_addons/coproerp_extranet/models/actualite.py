from odoo import fields, models


class Actualite(models.Model):
    _name = "coproerp.actualite"
    _description = "Actualité de la copropriété (extranet)"
    _order = "date_publication desc, id desc"

    name = fields.Char(string="Titre", required=True)
    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
        index=True,
    )
    contenu = fields.Html(string="Contenu", sanitize=True)
    date_publication = fields.Date(
        string="Date de publication",
        default=fields.Date.context_today,
        required=True,
    )
    date_fin = fields.Date(
        string="Afficher jusqu'au",
        help="Laisser vide pour un affichage sans limite.",
    )
    publie = fields.Boolean(string="Publiée", default=True)
    importance = fields.Selection(
        [("info", "Information"), ("alerte", "Alerte")],
        default="info",
        required=True,
    )
