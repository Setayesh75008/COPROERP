from odoo import api, fields, models
from odoo.exceptions import ValidationError

TYPES_INDICE = [("irl", "IRL"), ("ilc", "ILC"), ("ilat", "ILAT"), ("icc", "ICC")]
TRIMESTRES = [("1", "1er trimestre"), ("2", "2e trimestre"), ("3", "3e trimestre"), ("4", "4e trimestre")]


class Indice(models.Model):
    """Valeur trimestrielle d'un indice publié par l'INSEE."""

    _name = "coproerp.locatif.indice"
    _description = "Indice de révision des loyers"
    _order = "type_indice, annee desc, trimestre desc"

    name = fields.Char(string="Libellé", compute="_compute_name", store=True)
    type_indice = fields.Selection(TYPES_INDICE, string="Indice", required=True, default="irl")
    annee = fields.Integer(string="Année", required=True)
    trimestre = fields.Integer(string="Trimestre", required=True)
    valeur = fields.Float(string="Valeur", digits=(8, 2), required=True)
    date_publication = fields.Date(string="Publié le")

    @api.depends("type_indice", "annee", "trimestre")
    def _compute_name(self):
        for indice in self:
            indice.name = "%s T%s %s" % (dict(TYPES_INDICE).get(indice.type_indice, ""), indice.trimestre,
                                         indice.annee)

    @api.constrains("type_indice", "annee", "trimestre", "valeur")
    def _check_indice(self):
        for indice in self:
            if not 1 <= indice.trimestre <= 4:
                raise ValidationError("Le trimestre est compris entre 1 et 4.")
            if indice.valeur <= 0:
                raise ValidationError("La valeur de l'indice doit être positive.")
            if self.search_count([("type_indice", "=", indice.type_indice), ("annee", "=", indice.annee),
                                  ("trimestre", "=", indice.trimestre), ("id", "!=", indice.id)]):
                raise ValidationError("L'indice %s existe déjà." % indice.name)

    @api.model
    def trouver(self, type_indice, annee, trimestre):
        return self.search([("type_indice", "=", type_indice), ("annee", "=", annee),
                            ("trimestre", "=", int(trimestre))], limit=1)
