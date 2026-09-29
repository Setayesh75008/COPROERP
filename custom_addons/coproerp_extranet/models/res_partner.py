from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    extranet_notif_documents = fields.Boolean(
        string="Alerte e-mail : nouveaux documents",
        default=True,
    )

    mandat_cs_ids = fields.One2many(
        "coproerp.cs.mandat",
        "personne_id",
        string="Mandats au conseil syndical",
    )

    demat_consentement_ids = fields.One2many(
        "coproerp.demat.consentement",
        "personne_id",
        string="Accords de dématérialisation",
    )

    def _extranet_personnes(self):
        """Personnes dont l'utilisateur connecté peut voir les droits :
        lui-même et, s'il est le contact d'une société (SCI...), la société."""
        self.ensure_one()
        return self | self.commercial_partner_id
