from odoo import models, fields, api
from odoo.exceptions import ValidationError


class Repartition(models.Model):
    _name = "coproerp.repartition"
    _description = "Clé de répartition"
    _rec_name = "name"
    _order = "name"

    active = fields.Boolean(
        string="Actif",
        default=True,
    )

    name = fields.Char(
        string="Nom de la clé de répartition",
        required=True,
    )

    reference = fields.Char(
        string="Référence",
        readonly=True,
        copy=False,
        default="/",
    )

    type_repartition = fields.Selection(
        [
            (
                "charges_generales",
                "Charges communes générales",
            ),
            (
                "chauffage",
                "Chauffage",
            ),
            (
                "eau_chaude",
                "Eau chaude",
            ),
            (
                "ascenseur_escalier",
                "Ascenseur / escalier",
            ),
            (
                "fonds_travaux",
                "Fonds obligatoire travaux",
            ),
            (
                "travaux_exceptionnels",
                "Travaux exceptionnels",
            ),
            (
                "autre",
                "Autre",
            ),
        ],
        string="Type de répartition",
        required=True,
        default="charges_generales",
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
    )

    total_tantiemes = fields.Integer(
        string="Total théorique des tantièmes",
        default=10000,
        required=True,
    )

    total_attribue = fields.Integer(
        string="Tantièmes attribués",
        compute="_compute_totaux",
        store=True,
    )

    ecart_tantiemes = fields.Integer(
        string="Écart",
        compute="_compute_totaux",
        store=True,
    )

    etat_repartition = fields.Selection(
        [
            (
                "incomplet",
                "Incomplet",
            ),
            (
                "complet",
                "Complet",
            ),
            (
                "depassement",
                "Dépassement",
            ),
        ],
        string="État",
        compute="_compute_totaux",
        store=True,
    )

    line_ids = fields.One2many(
        "coproerp.repartition.lot",
        "repartition_id",
        string="Répartition des tantièmes par lot",
    )

    note = fields.Text(
        string="Observations",
    )

    @api.depends(
        "total_tantiemes",
        "line_ids.tantiemes",
    )
    def _compute_totaux(self):
        for repartition in self:
            total_attribue = sum(
                repartition.line_ids.mapped("tantiemes")
            )

            repartition.total_attribue = total_attribue

            repartition.ecart_tantiemes = (
                repartition.total_tantiemes
                - total_attribue
            )

            if total_attribue == repartition.total_tantiemes:
                repartition.etat_repartition = "complet"

            elif total_attribue < repartition.total_tantiemes:
                repartition.etat_repartition = "incomplet"

            else:
                repartition.etat_repartition = "depassement"

    @api.constrains("total_tantiemes")
    def _check_total_tantiemes(self):
        for repartition in self:
            if repartition.total_tantiemes <= 0:
                raise ValidationError(
                    "Le total théorique des tantièmes doit être "
                    "supérieur à zéro."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("reference", "/") == "/":
                vals["reference"] = (
                    self.env["ir.sequence"].next_by_code(
                        "coproerp.repartition"
                    )
                    or "/"
                )

        return super().create(vals_list)


class RepartitionLot(models.Model):
    _name = "coproerp.repartition.lot"
    _description = "Répartition d'un lot"
    _order = "lot_id"

    repartition_id = fields.Many2one(
        "coproerp.repartition",
        string="Clé de répartition",
        required=True,
        ondelete="cascade",
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        related="repartition_id.copropriete_id",
        store=True,
        readonly=True,
    )

    lot_id = fields.Many2one(
        "coproerp.lot",
        string="Lot",
        required=True,
        ondelete="cascade",
        domain="[('copropriete_id', '=', copropriete_id)]",
    )

    lot_numero = fields.Char(
        string="N° de lot",
        related="lot_id.numero",
        store=True,
        readonly=True,
    )

    lot_designation = fields.Char(
        string="Désignation",
        related="lot_id.designation",
        store=True,
        readonly=True,
    )

    tantiemes = fields.Integer(
        string="Tantièmes",
        required=True,
        default=0,
    )

    pourcentage = fields.Float(
        string="Quote-part (%)",
        compute="_compute_pourcentage",
        store=True,
        digits=(16, 4),
    )

    @api.depends(
        "tantiemes",
        "repartition_id.total_tantiemes",
    )
    def _compute_pourcentage(self):
        for line in self:
            total = line.repartition_id.total_tantiemes

            if total:
                line.pourcentage = (
                    line.tantiemes / total
                ) * 100

            else:
                line.pourcentage = 0.0

    @api.constrains("tantiemes")
    def _check_tantiemes(self):
        for line in self:
            if line.tantiemes < 0:
                raise ValidationError(
                    "Les tantièmes d'un lot ne peuvent pas être négatifs."
                )

    @api.constrains(
        "repartition_id",
        "lot_id",
    )
    def _check_unique_repartition_lot(self):
        for line in self:
            duplicate = self.search_count(
                [
                    (
                        "id",
                        "!=",
                        line.id,
                    ),
                    (
                        "repartition_id",
                        "=",
                        line.repartition_id.id,
                    ),
                    (
                        "lot_id",
                        "=",
                        line.lot_id.id,
                    ),
                ]
            )

            if duplicate:
                raise ValidationError(
                    "Un lot ne peut apparaître qu'une seule fois "
                    "dans une clé de répartition."
                )
