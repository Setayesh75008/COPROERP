from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError


class ReleveCompteWizard(models.TransientModel):
    _name = "coproerp.releve.wizard"
    _description = "Impression de relevés de compte copropriétaires"

    copropriete_id = fields.Many2one("coproerp.copropriete", string="Copropriété", required=True)
    personne_ids = fields.Many2many("res.partner", string="Copropriétaires")
    date_debut = fields.Date(
        string="Du", required=True,
        default=lambda self: date(fields.Date.context_today(self).year, 1, 1),
    )
    date_fin = fields.Date(string="Au", required=True, default=fields.Date.context_today)

    @api.model
    def _personnes_de(self, copro):
        return copro.droit_ids.filtered("acces_extranet").personne_id

    @api.model
    def default_get(self, fields_list):
        valeurs = super().default_get(fields_list)
        modele = self.env.context.get("active_model")
        ids = self.env.context.get("active_ids") or []
        if modele == "coproerp.copropriete" and ids:
            copro = self.env["coproerp.copropriete"].browse(ids[:1])
            valeurs.setdefault("copropriete_id", copro.id)
            valeurs.setdefault("personne_ids", [(6, 0, self._personnes_de(copro).ids)])
        elif modele == "res.partner" and ids:
            valeurs.setdefault("personne_ids", [(6, 0, ids)])
            droit = self.env["coproerp.droit"].search([("personne_id", "in", ids)], limit=1)
            if droit:
                valeurs.setdefault("copropriete_id", droit.copropriete_id.id)
        return valeurs

    @api.onchange("copropriete_id")
    def _onchange_copropriete_id(self):
        if self.copropriete_id and not self.personne_ids:
            self.personne_ids = self._personnes_de(self.copropriete_id)

    def action_imprimer(self):
        self.ensure_one()
        if self.date_debut > self.date_fin:
            raise UserError("La date de début doit précéder la date de fin.")
        if not self.personne_ids:
            raise UserError("Choisissez au moins un copropriétaire.")
        self.copropriete_id._verifier_dossier()
        return self.env.ref("coproerp_comptabilite.action_report_releve_compte").report_action(
            self.copropriete_id,
            data={
                "personne_ids": self.personne_ids.ids,
                "date_debut": fields.Date.to_string(self.date_debut),
                "date_fin": fields.Date.to_string(self.date_fin),
            },
        )
