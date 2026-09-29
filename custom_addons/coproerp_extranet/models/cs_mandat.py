from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ConseilSyndicalMandat(models.Model):
    _name = "coproerp.cs.mandat"
    _description = "Mandat de membre du conseil syndical"
    _inherit = ["mail.thread"]
    _order = "copropriete_id, date_debut desc"
    _rec_name = "personne_id"

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    personne_id = fields.Many2one(
        "res.partner",
        string="Membre",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    fonction = fields.Selection(
        [
            ("president", "Président"),
            ("membre", "Membre"),
            ("suppleant", "Suppléant"),
        ],
        string="Fonction",
        required=True,
        default="membre",
        tracking=True,
    )

    date_debut = fields.Date(
        string="Début du mandat",
        required=True,
        tracking=True,
        help="Date de l'assemblée générale ayant désigné le membre.",
    )

    date_fin = fields.Date(
        string="Fin du mandat",
        tracking=True,
        help="Laisser vide tant que la date de fin n'est pas connue. "
        "Le mandat ne peut excéder trois ans (art. 22 du décret du 17 mars 1967).",
    )

    date_ag_designation = fields.Date(string="Date de l'AG de désignation")

    active = fields.Boolean(default=True)

    # Stocké pour être utilisable dans les règles d'accès ; mis à jour à
    # chaque modification et chaque nuit.
    en_cours = fields.Boolean(
        string="Mandat en cours",
        readonly=True,
        copy=False,
        index=True,
    )

    note = fields.Text(string="Observations")

    @api.constrains("date_debut", "date_fin")
    def _check_dates(self):
        for mandat in self:
            if mandat.date_fin and mandat.date_fin < mandat.date_debut:
                raise ValidationError(
                    "La fin du mandat ne peut pas précéder son début."
                )

    def _maj_en_cours(self):
        today = fields.Date.context_today(self)
        for mandat in self.with_context(active_test=False):
            valeur = bool(
                mandat.active
                and mandat.date_debut
                and mandat.date_debut <= today
                and (not mandat.date_fin or mandat.date_fin >= today)
            )
            if mandat.en_cours != valeur:
                super(ConseilSyndicalMandat, mandat).write({"en_cours": valeur})

    @api.model_create_multi
    def create(self, vals_list):
        mandats = super().create(vals_list)
        mandats._maj_en_cours()
        return mandats

    def write(self, vals):
        res = super().write(vals)
        if {"active", "date_debut", "date_fin"} & set(vals):
            self._maj_en_cours()
        return res

    @api.model
    def _cron_maj_en_cours(self):
        self.with_context(active_test=False).search([])._maj_en_cours()
