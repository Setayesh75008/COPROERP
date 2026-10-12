from odoo import api, fields, models


class ReportReleveCompte(models.AbstractModel):
    """Valeurs du rapport « Relevé de compte » (un relevé par copropriétaire)."""

    _name = "report.coproerp_comptabilite.report_releve_compte"
    _description = "Relevé de compte copropriétaire"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        # Avec des données (« data »), le client web n'ajoute pas les
        # identifiants des documents à l'adresse d'impression : on les
        # transmet donc aussi dans les données.
        docids = docids or data.get("copropriete_ids") or []
        coproprietes = self.env["coproerp.copropriete"].browse(docids)
        aujourdhui = fields.Date.context_today(self)
        date_debut = data.get("date_debut") or aujourdhui.replace(month=1, day=1)
        date_fin = data.get("date_fin") or aujourdhui
        releves = [
            copro.donnees_releve(personne_id, date_debut, date_fin)
            for copro in coproprietes
            for personne_id in data.get("personne_ids") or []
        ]
        return {
            "doc_ids": docids,
            "doc_model": "coproerp.copropriete",
            "docs": coproprietes,
            "releves": releves,
        }
