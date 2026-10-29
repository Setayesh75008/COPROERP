from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class TauxLegal(models.Model):
    """Taux de l'intérêt légal par semestre (art. L. 313-2 du code monétaire et financier)."""

    _name = "coproerp.taux.legal"
    _description = "Taux de l'intérêt légal"
    _order = "date_debut desc"
    _rec_name = "date_debut"

    date_debut = fields.Date(string="Du", required=True)
    date_fin = fields.Date(string="Au", required=True)
    taux_particuliers = fields.Float(
        string="Créancier personne physique (hors besoins professionnels) %", digits=(6, 2), required=True)
    taux_autres = fields.Float(string="Tous les autres cas %", digits=(6, 2), required=True,
                               help="Taux applicable au syndicat des copropriétaires, personne morale créancière.")

    @api.constrains("date_debut", "date_fin")
    def _check_periode(self):
        for taux in self:
            if taux.date_fin < taux.date_debut:
                raise ValidationError("La fin de la période précède son début.")
            if self.search_count([("id", "!=", taux.id), ("date_debut", "<=", taux.date_fin),
                                  ("date_fin", ">=", taux.date_debut)]):
                raise ValidationError("Les périodes de taux ne peuvent pas se chevaucher.")

    @api.model
    def periode_au(self, date):
        taux = self.search([("date_debut", "<=", date), ("date_fin", ">=", date)], limit=1)
        if not taux:
            raise UserError("Le taux de l'intérêt légal n'est pas renseigné pour le %s : complétez la table "
                            "(Comptabilité → Recouvrement → Taux de l'intérêt légal)." % date.strftime("%d/%m/%Y"))
        return taux
