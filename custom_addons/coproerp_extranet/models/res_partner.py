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

    # --- Notifications (art. 42-1 loi 1965, art. 64 et 65 décret 1967) ---
    email_notification = fields.Char(
        string="Adresse électronique de notification",
        help="Adresse communiquée par le copropriétaire à cet effet (art. 65 du décret du "
        "17 mars 1967). Distincte de l'adresse de connexion à l'espace en ligne.",
    )
    notification_mode_ids = fields.One2many(
        "coproerp.notification.mode", "personne_id", string="Choix de réception des notifications"
    )
    mode_notification = fields.Selection(
        [("electronique", "Voie électronique"), ("postal", "Voie postale")],
        string="Réception des notifications",
        compute="_compute_mode_notification",
    )

    def _compute_mode_notification(self):
        Mode = self.env["coproerp.notification.mode"]
        for partner in self:
            partner.mode_notification = Mode.mode_au(partner)[0] if partner.id else "postal"

    def _extranet_personnes(self):
        """Personnes dont l'utilisateur connecté peut voir les droits :
        lui-même et, s'il est le contact d'une société (SCI...), la société."""
        self.ensure_one()
        return self | self.commercial_partner_id
