from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from .indice import TRIMESTRES


class Bail(models.Model):
    _inherit = "coproerp.locatif.bail"

    indice_trimestre = fields.Selection(TRIMESTRES, string="Trimestre de l'indice de référence")
    indice_annee = fields.Integer(string="Année de l'indice de référence")
    date_derniere_revision = fields.Date(string="Dernière révision", readonly=True, copy=False)
    date_prochaine_revision = fields.Date(string="Prochaine révision", compute="_compute_prochaine_revision")
    revision_ids = fields.One2many("coproerp.locatif.revision", "bail_id", string="Révisions")
    regularisation_ids = fields.One2many("coproerp.locatif.regularisation", "bail_id",
                                         string="Régularisations des charges")

    @api.depends("date_debut", "date_derniere_revision", "indice")
    def _compute_prochaine_revision(self):
        for bail in self:
            if not bail.date_debut or bail.indice == "aucun":
                bail.date_prochaine_revision = False
                continue
            reference = bail.date_derniere_revision or bail.date_debut
            prochaine = bail.date_debut + relativedelta(years=1)
            while prochaine <= reference:
                prochaine += relativedelta(years=1)
            bail.date_prochaine_revision = prochaine

    @api.onchange("indice", "indice_trimestre", "indice_annee")
    def _onchange_indice_reference(self):
        if self.indice and self.indice != "aucun" and self.indice_trimestre and self.indice_annee:
            indice = self.env["coproerp.locatif.indice"].trouver(self.indice, self.indice_annee, self.indice_trimestre)
            if indice:
                self.valeur_indice = indice.valeur
                self.trimestre_reference = "T%s %s" % (self.indice_trimestre, self.indice_annee)

    def action_preparer_revision(self):
        self.ensure_one()
        revision = self.env["coproerp.locatif.revision"].preparer(self)
        return {"type": "ir.actions.act_window", "res_model": "coproerp.locatif.revision", "res_id": revision.id,
                "view_mode": "form"}

    def action_nouvelle_regularisation(self):
        self.ensure_one()
        regularisation = self.env["coproerp.locatif.regularisation"].create({"bail_id": self.id})
        regularisation.action_calculer_provisions()
        return {"type": "ir.actions.act_window", "res_model": "coproerp.locatif.regularisation",
                "res_id": regularisation.id, "view_mode": "form"}
