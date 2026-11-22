from datetime import timedelta

from odoo import fields, models

FINS_DE_TRIMESTRE = (3, 6, 9, 12)


class PreparationComptesRendus(models.TransientModel):
    """Établit en une fois les comptes rendus de gestion de la période et prépare les virements."""

    _name = "coproerp.locatif.preparation.crg"
    _description = "Préparation des comptes rendus de gestion"

    def _fin_mois_precedent(self):
        return fields.Date.context_today(self).replace(day=1) - timedelta(days=1)

    date_fin = fields.Date(string="Comptes rendus arrêtés au", required=True, default=_fin_mois_precedent)
    mandat_ids = fields.Many2many("coproerp.locatif.mandat", string="Mandats",
                                  domain="[('etat', '=', 'actif')]", help="Laisser vide pour tous les mandats en cours.")
    preparer_virements = fields.Boolean(string="Préparer les virements du disponible", default=True)

    def action_preparer(self):
        self.ensure_one()
        CompteRendu = self.env["coproerp.locatif.compte_rendu"]
        mandats = self.mandat_ids or self.env["coproerp.locatif.mandat"].search([("etat", "=", "actif")])
        crgs = CompteRendu
        for mandat in mandats:
            if mandat.reversement == "trimestriel" and self.date_fin.month not in FINS_DE_TRIMESTRE:
                continue
            debut = CompteRendu.debut_suivant(mandat)
            if not debut or debut > self.date_fin:
                continue
            crg = CompteRendu.create({"mandat_id": mandat.id, "date_debut": debut, "date_fin": self.date_fin})
            crg.action_valider()
            if self.preparer_virements:
                crg.action_preparer_virement()
            crgs |= crg
        return {"type": "ir.actions.act_window", "name": "Comptes rendus établis",
                "res_model": "coproerp.locatif.compte_rendu", "view_mode": "list,form",
                "domain": [("id", "in", crgs.ids)]}
