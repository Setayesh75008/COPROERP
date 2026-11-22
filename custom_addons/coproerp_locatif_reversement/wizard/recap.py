from odoo import fields, models
from odoo.exceptions import UserError


class RecapFiscalWizard(models.TransientModel):
    _name = "coproerp.locatif.recap.fiscal"
    _description = "Récapitulatif annuel des revenus fonciers"

    annee = fields.Integer(string="Année des revenus", required=True,
                           default=lambda self: fields.Date.context_today(self).year - 1)
    proprietaire_ids = fields.Many2many("res.partner", string="Propriétaires",
                                        domain="[('role_bailleur', '=', True)]",
                                        help="Laisser vide pour tous les propriétaires ayant un mandat.")

    def action_imprimer(self):
        self.ensure_one()
        proprietaires = self.proprietaire_ids or self.env["coproerp.locatif.mandat"].search(
            [("etat", "!=", "brouillon")]).proprietaire_id
        if not proprietaires:
            raise UserError("Aucun propriétaire sous mandat.")
        return self.env.ref("coproerp_locatif_reversement.action_report_recap_fiscal").report_action(
            proprietaires, data={"annee": self.annee, "proprietaire_ids": proprietaires.ids})
