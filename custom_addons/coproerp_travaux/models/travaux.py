# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CoproerpTravaux(models.Model):
    _name = "coproerp.travaux"
    _description = "Travaux votés en copropriété"
    _rec_name = "reference"
    _order = "date_vote desc, id desc"

    active = fields.Boolean(
        string="Actif",
        default=True,
    )

    reference = fields.Char(
        string="Référence",
        required=True,
        copy=False,
        readonly=True,
        default="Nouveau",
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="restrict",
    )

    name = fields.Char(
        string="Désignation des travaux",
        required=True,
    )

    description = fields.Text(
        string="Description",
    )

    date_vote = fields.Date(
        string="Date du vote",
        required=True,
    )

    resolution_ag = fields.Char(
        string="Résolution AG",
        help="Numéro ou référence de la résolution ayant approuvé les travaux.",
    )

    montant_vote = fields.Float(
        string="Montant voté",
        required=True,
        digits=(16, 2),
    )

    date_debut_prevue = fields.Date(
        string="Début prévisionnel",
    )

    date_fin_prevue = fields.Date(
        string="Fin prévisionnelle",
    )

    etat = fields.Selection(
        [
            ("projet", "Projet"),
            ("vote", "Voté"),
            ("financement", "Financement en cours"),
            ("en_cours", "En cours"),
            ("termine", "Terminé"),
            ("cloture", "Clôturé"),
            ("annule", "Annulé"),
        ],
        string="État",
        required=True,
        default="projet",
    )

    note = fields.Text(
        string="Observations",
    )

    financement_ids = fields.One2many(
        "coproerp.travaux.financement",
        "travaux_id",
        string="Financements",
    )
       
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("reference", "Nouveau") == "Nouveau":
                vals["reference"] = (
                    self.env["ir.sequence"].next_by_code("coproerp.travaux")
                    or "Nouveau"
                )

        return super().create(vals_list)

    @api.constrains("montant_vote")
    def _check_montant_vote(self):
        for record in self:
            if record.montant_vote <= 0:
                raise ValidationError(
                    "Le montant voté des travaux doit être supérieur à zéro."
                )

    @api.constrains("date_debut_prevue", "date_fin_prevue")
    def _check_dates(self):
        for record in self:
            if (
                record.date_debut_prevue
                and record.date_fin_prevue
                and record.date_fin_prevue < record.date_debut_prevue
            ):
                raise ValidationError(
                    "La date de fin prévisionnelle doit être postérieure "
                    "ou égale à la date de début prévisionnelle."
                )

    @api.constrains("date_vote")
    def _check_date_vote(self):
        for record in self:
            if not record.date_vote:
                raise ValidationError(
                    "La date du vote est obligatoire."
                )