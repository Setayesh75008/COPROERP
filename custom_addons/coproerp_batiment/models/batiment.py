from odoo import models, fields

class Batiment(models.Model):
    _name = "coproerp.batiment"
    _description = "Bâtiment"
    _rec_name = "name"
    _order = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(
        string="Nom du bâtiment",
        required=True,
    )

    reference = fields.Char(
        string="Référence",
        copy=False,
        readonly=True,
    )

    adresse = fields.Char(
        string="Adresse"
    )

    nombre_niveaux = fields.Integer(
        string="Nombre de niveaux",
        default=1,
    )

    nombre_logements = fields.Integer(
        string="Nombre de logements",
        default=0,
    )

    nombre_locaux = fields.Integer(
        string="Locaux commerciaux",
        default=0,
    )

    note = fields.Text(
        string="Observations"
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
    )
    
      
    image_1920 = fields.Image(
        string="Photo",
        max_width=1920,
        max_height=1920,
    )