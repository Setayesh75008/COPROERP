from odoo import fields, models


class Echeance(models.Model):
    _inherit = "coproerp.locatif.echeance"

    type_echeance = fields.Selection(selection_add=[("sortie", "Décompte de sortie")],
                                     ondelete={"sortie": "set default"})

    def libelle_periode(self):
        self.ensure_one()
        if self.type_echeance == "sortie":
            return "décompte de sortie du %s" % self.periode_fin.strftime("%d/%m/%Y")
        return super().libelle_periode()
