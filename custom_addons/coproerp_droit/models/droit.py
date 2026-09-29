from odoo import models, fields, api
from odoo.exceptions import ValidationError


class Droit(models.Model):
    _name = "coproerp.droit"
    _description = "Droit sur un lot"
    _rec_name = "reference"
    _order = "reference"

    active = fields.Boolean(
        string="Actif",
        default=True,
    )

    reference = fields.Char(
        string="Référence",
        readonly=True,
        copy=False,
        default="/",
    )

    personne_id = fields.Many2one(
        "res.partner",
        string="Personne",
        required=True,
        ondelete="cascade",
    )

    lot_id = fields.Many2one(
        "coproerp.lot",
        string="Lot",
        required=True,
        ondelete="cascade",
    )

    lot_numero = fields.Char(
        string="N° de lot",
        related="lot_id.numero",
        store=True,
        readonly=True,
    )

    lot_designation = fields.Char(
        string="Désignation du lot",
        related="lot_id.designation",
        store=True,
        readonly=True,
    )

    type_droit = fields.Selection(
        [
            ("proprietaire", "Propriétaire"),
            ("locataire", "Locataire"),
            ("usufruitier", "Usufruitier"),
            ("nu_proprietaire", "Nu-propriétaire"),
            ("indivisaire", "Indivisaire"),
        ],
        string="Type de droit",
        default="proprietaire",
        required=True,
    )

    quotite = fields.Float(
        string="Quote-part du droit (%)",
        default=100.0,
    )

    date_debut = fields.Date(
        string="Date de début",
    )

    date_fin = fields.Date(
        string="Date de fin",
    )

    note = fields.Text(
        string="Observations",
    )

    @api.constrains("quotite")
    def _check_quotite(self):
        for droit in self:
            if droit.quotite <= 0 or droit.quotite > 100:
                raise ValidationError(
                    "La quote-part du droit doit être comprise entre "
                    "0 et 100 %."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("reference", "/") == "/":
                vals["reference"] = (
                    self.env["ir.sequence"].next_by_code("coproerp.droit")
                    or "/"
                )

        return super().create(vals_list)