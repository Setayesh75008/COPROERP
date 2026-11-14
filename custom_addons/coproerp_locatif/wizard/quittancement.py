from datetime import timedelta

from odoo import fields, models


class Quittancement(models.TransientModel):
    """Émission groupée des avis d'échéance."""

    _name = "coproerp.locatif.quittancement"
    _description = "Quittancement des loyers"

    date_limite = fields.Date(string="Émettre les avis exigibles jusqu'au", required=True,
                              default=lambda self: fields.Date.context_today(self) + timedelta(days=15))
    bail_ids = fields.Many2many("coproerp.locatif.bail", string="Baux (vide = tous les baux en cours)",
                                domain="[('etat', '=', 'en_cours')]")
    resultat = fields.Text(string="Résultat", readonly=True)

    def action_emettre(self):
        self.ensure_one()
        self.env["coproerp.locatif.dossier"].actif()
        baux = self.bail_ids or self.env["coproerp.locatif.bail"].search([("etat", "=", "en_cours")])
        avis = baux.generer_echeances(self.date_limite)
        total = sum(avis.mapped("montant_total"))
        self.resultat = "%d avis d'échéance émis pour %d bail(s), total %s." % (
            len(avis), len(avis.bail_id), self.env["coproerp.locatif.bail"].euros(total))
        return {
            "type": "ir.actions.act_window", "name": "Avis émis", "res_model": "coproerp.locatif.echeance",
            "view_mode": "list,form", "domain": [("id", "in", avis.ids)],
        }
