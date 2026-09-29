from odoo import models, fields, api


class Lot(models.Model):
    _name = "coproerp.lot"
    _description = "Lot"
    _rec_name = "designation"
    _order = "numero"

    active = fields.Boolean(
        string="Actif",
        default=True,
    )

    numero = fields.Char(
        string="Numéro de lot",
        required=True,
    )

    designation = fields.Char(
        string="Désignation",
        required=True,
    )

    batiment_id = fields.Many2one(
        "coproerp.batiment",
        string="Bâtiment",
        required=True,
        ondelete="restrict",
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        related="batiment_id.copropriete_id",
        store=True,
        readonly=True,
    )

    proprietaire_ids = fields.Many2many(
        "res.partner",
        "coproerp_lot_proprietaire_rel",
        "lot_id",
        "partner_id",
        string="Propriétaires",
    )

    occupant_ids = fields.Many2many(
        "res.partner",
        "coproerp_lot_occupant_rel",
        "lot_id",
        "partner_id",
        string="Occupants",
    )

    type_lot = fields.Selection(
        [
            ("principal", "Lot principal"),
            ("secondaire", "Lot secondaire"),
        ],
        string="Nature du lot",
        default="principal",
        required=True,
    )

    usage = fields.Selection(
        [
            ("appartement", "Appartement"),
            ("parking", "Parking"),
            ("cave", "Cave"),
            ("local", "Local commercial"),
            ("bureau", "Bureau"),
            ("cellier", "Cellier"),
            ("jardin", "Jardin"),
            ("autre", "Autre"),
        ],
        string="Usage",
        default="appartement",
    )

    surface = fields.Float(
        string="Surface privative (m²)",
    )

    etage = fields.Char(
        string="Étage",
    )

    tantiemes = fields.Integer(
        string="Tantièmes de référence",
        default=0,
    )

    note = fields.Text(
        string="Observations",
    )

    @api.depends("numero", "designation", "usage")
    def _compute_display_name(self):
        for lot in self:
            if lot.numero and lot.designation:
                lot.display_name = f"Lot {lot.numero} — {lot.designation}"
            elif lot.numero:
                lot.display_name = f"Lot {lot.numero}"
            elif lot.designation:
                lot.display_name = lot.designation
            else:
                lot.display_name = "Lot"