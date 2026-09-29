# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CoproerpTravauxFinancement(models.Model):
    _name = "coproerp.travaux.financement"
    _description = "Financement des travaux de copropriété"
    _order = "id"

    active = fields.Boolean(
        string="Actif",
        default=True,
    )

    travaux_id = fields.Many2one(
        "coproerp.travaux",
        string="Travaux",
        required=True,
        ondelete="cascade",
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        related="travaux_id.copropriete_id",
        store=True,
        readonly=True,
    )

    type_financement = fields.Selection(
        [
            ("fonds_travaux", "Fonds travaux"),
            ("appel_exceptionnel", "Appel exceptionnel"),
            ("emprunt", "Emprunt"),
            ("autre", "Autre financement"),
        ],
        string="Type de financement",
        required=True,
        default="appel_exceptionnel",
    )

    name = fields.Char(
        string="Désignation",
        required=True,
    )

    montant_prevu = fields.Float(
        string="Montant prévu",
        required=True,
        digits=(16, 2),
    )

    nombre_appels = fields.Integer(
        string="Nombre d'appels",
        required=True,
        default=1,
    )

    montant_par_appel = fields.Float(
        string="Montant par appel",
        compute="_compute_montant_par_appel",
        store=True,
        digits=(16, 2),
    )

    repartition_id = fields.Many2one(
        "coproerp.repartition",
        string="Répartition",
        domain="[('copropriete_id', '=', copropriete_id)]",
        ondelete="restrict",
    )

    date_prevue = fields.Date(
        string="Date prévue",
    )

    note = fields.Text(
        string="Observations",
    )

    @api.depends("montant_prevu", "nombre_appels")
    def _compute_montant_par_appel(self):
        for record in self:
            if record.nombre_appels > 0:
                record.montant_par_appel = (
                    record.montant_prevu / record.nombre_appels
                )
            else:
                record.montant_par_appel = 0.0

    @api.constrains("montant_prevu")
    def _check_montant_prevu(self):
        for record in self:
            if record.montant_prevu <= 0:
                raise ValidationError(
                    "Le montant prévu du financement doit être supérieur à zéro."
                )

    @api.constrains("nombre_appels")
    def _check_nombre_appels(self):
        for record in self:
            if record.nombre_appels < 1:
                raise ValidationError(
                    "Le nombre d'appels doit être au moins égal à 1."
                )

    @api.constrains("repartition_id", "copropriete_id")
    def _check_repartition_copropriete(self):
        for record in self:
            if (
                record.repartition_id
                and record.copropriete_id
                and record.repartition_id.copropriete_id
                != record.copropriete_id
            ):
                raise ValidationError(
                    "La répartition doit appartenir à la même copropriété que les travaux."
                )
