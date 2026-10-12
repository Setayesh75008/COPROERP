from datetime import date

from odoo import fields, http
from odoo.http import content_disposition, request

from odoo.addons.coproerp_extranet.controllers.main import ExtranetPortal


class ExtranetReleveCompte(ExtranetPortal):

    @http.route(["/extranet/situation/releve"], type="http", auth="user", website=True)
    def extranet_releve_pdf(self, du=None, au=None, **kw):
        """Relevé de compte PDF du copropriétaire connecté (ses propres comptes uniquement)."""
        values = self._ext_values("situation")
        copro = values["copro"]
        if not copro or not copro.sudo().company_id:
            raise request.not_found()
        aujourdhui = fields.Date.context_today(request.env.user)
        try:
            date_fin = fields.Date.to_date(au) if au else aujourdhui
            date_debut = fields.Date.to_date(du) if du else date(aujourdhui.year, 1, 1)
        except ValueError:
            raise request.not_found()
        if date_debut > date_fin:
            raise request.not_found()
        titulaires = copro.sudo().droit_ids.filtered("acces_extranet").personne_id & self._ext_personnes()
        if not titulaires:
            raise request.not_found()
        pdf, _type = request.env["ir.actions.report"].sudo()._render_qweb_pdf(
            "coproerp_comptabilite.report_releve_compte",
            [copro.id],
            data={
                "copropriete_ids": copro.ids,
                "personne_ids": titulaires.ids,
                "date_debut": fields.Date.to_string(date_debut),
                "date_fin": fields.Date.to_string(date_fin),
            },
        )
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(pdf)),
            ("Content-Disposition", content_disposition("releve_de_compte.pdf")),
        ])
