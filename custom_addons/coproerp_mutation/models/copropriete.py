from odoo import api, fields, models
from odoo.exceptions import ValidationError

PLAFOND_ETAT_DATE = 380.0  # € TTC (art. 10-1 de la loi, décret n° 2020-153 du 21 février 2020)


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    mutation_honoraires_etat_date = fields.Float(
        string="Honoraires d'état daté (€ TTC)", digits=(16, 2), default=PLAFOND_ETAT_DATE,
        help="Montant prévu au contrat de syndic, imputé au seul vendeur (art. 10-1 de la loi). "
             "Plafonné à 380 € TTC.",
    )

    @api.constrains("mutation_honoraires_etat_date")
    def _check_honoraires_etat_date(self):
        for copro in self:
            if copro.mutation_honoraires_etat_date > PLAFOND_ETAT_DATE + 0.001:
                raise ValidationError("Les honoraires d'état daté sont plafonnés à 380 € TTC.")
