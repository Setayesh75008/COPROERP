from odoo import fields, models


class Echeance(models.Model):
    _inherit = "coproerp.locatif.echeance"

    type_echeance = fields.Selection(
        selection_add=[("revision", "Rappel de révision du loyer"),
                       ("regularisation", "Régularisation des charges")],
        ondelete={"revision": "set default", "regularisation": "set default"})

    def libelle_periode(self):
        self.ensure_one()
        if self.type_echeance == "revision":
            return "rappel de révision du loyer à compter du %s" % self.periode_debut.strftime("%d/%m/%Y")
        if self.type_echeance == "regularisation":
            return "régularisation des charges du %s au %s" % (
                self.periode_debut.strftime("%d/%m/%Y"), self.periode_fin.strftime("%d/%m/%Y"))
        return super().libelle_periode()
