from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Délai de prise en compte d'une demande (décret du 17 mars 1967 modifié par le
# décret n° 2025-1292 du 22 décembre 2025) : la demande prend effet le 9e jour
# suivant sa réception par le syndic, ou immédiatement si elle est formulée en
# assemblée générale (elle est alors mentionnée au procès-verbal).
DELAI_EFFET_JOURS = 9

MENTION_VOIE_POSTALE = (
    "Conformément à l'article 42-1 de la loi n° 65-557 du 10 juillet 1965, les notifications "
    "et mises en demeure vous sont adressées par voie électronique. Vous pouvez à tout moment "
    "demander à les recevoir par voie postale, par tout moyen permettant d'établir la date de "
    "réception de votre demande par le syndic, notamment depuis votre espace en ligne "
    "(rubrique « Réception des notifications »)."
)


class NotificationMode(models.Model):
    """Journal (non modifiable) des choix de réception des notifications.

    Régime de l'art. 42-1 de la loi du 10 juillet 1965 (loi n° 2024-322 du
    9 avril 2024) : la voie électronique est le principe ; le copropriétaire
    peut à tout moment demander la voie postale. Chaque ligne conserve la date
    de réception de la demande, son origine et sa date d'effet.
    """

    _name = "coproerp.notification.mode"
    _description = "Choix de réception des notifications"
    _order = "date_effet desc, id desc"

    personne_id = fields.Many2one(
        "res.partner", string="Copropriétaire", required=True, ondelete="cascade", index=True
    )
    objet = fields.Selection(
        [
            ("postal", "Demande de réception par voie postale"),
            ("electronique", "Retour à la voie électronique"),
            ("adresse", "Communication d'une adresse électronique de notification"),
        ],
        string="Objet",
        required=True,
    )
    email = fields.Char(string="Adresse électronique de notification")
    origine = fields.Selection(
        [
            ("extranet", "Espace en ligne (par le copropriétaire)"),
            ("ag", "Assemblée générale (mention au procès-verbal)"),
            ("courrier", "Courrier"),
            ("email", "Courrier électronique"),
            ("syndic", "Autre (saisie par le syndic)"),
        ],
        string="Origine",
        required=True,
        default="courrier",
    )
    date_reception = fields.Date(
        string="Reçue par le syndic le", required=True, default=fields.Date.context_today
    )
    date_effet = fields.Date(
        string="Prend effet le", compute="_compute_date_effet", store=True, index=True
    )
    date = fields.Datetime(string="Enregistrée le", default=fields.Datetime.now, required=True, readonly=True)
    adresse_ip = fields.Char(string="Adresse IP", readonly=True)
    user_agent = fields.Char(string="Navigateur", readonly=True)
    utilisateur_id = fields.Many2one(
        "res.users", string="Enregistrée par", default=lambda self: self.env.user, readonly=True
    )
    note = fields.Char(string="Observations")

    @api.depends("date_reception", "origine", "objet")
    def _compute_date_effet(self):
        for ligne in self:
            if not ligne.date_reception:
                ligne.date_effet = False
            elif ligne.origine == "ag" or ligne.objet == "adresse":
                ligne.date_effet = ligne.date_reception
            else:
                ligne.date_effet = ligne.date_reception + timedelta(days=DELAI_EFFET_JOURS)

    @api.constrains("objet", "email")
    def _check_email(self):
        for ligne in self:
            if ligne.objet == "adresse" and not (ligne.email or "").strip():
                raise ValidationError("Indiquez l'adresse électronique communiquée.")

    @api.constrains("date_reception")
    def _check_date(self):
        for ligne in self:
            if ligne.date_reception and ligne.date_reception > fields.Date.context_today(ligne):
                raise ValidationError("La date de réception ne peut pas être dans le futur.")

    @api.model_create_multi
    def create(self, vals_list):
        lignes = super().create(vals_list)
        for ligne in lignes.filtered(lambda l: l.objet == "adresse"):
            ligne.personne_id.sudo().email_notification = ligne.email.strip()
        return lignes

    def write(self, vals):
        raise UserError(
            "Le journal des choix de réception ne peut pas être modifié : "
            "enregistrez une nouvelle demande."
        )

    def unlink(self):
        raise UserError("Le journal des choix de réception ne peut pas être supprimé.")

    @api.model
    def mode_au(self, partner, date=None):
        """Mode de réception applicable à ``partner`` à la date ``date``.

        Retourne (mode, adresse) : ('electronique', adresse) ou ('postal', False).
        Sans adresse électronique de notification, la voie postale s'impose.
        """
        date = date or fields.Date.context_today(self)
        derniere = self.sudo().search([
            ("personne_id", "=", partner.id),
            ("objet", "in", ("postal", "electronique")),
            ("date_effet", "<=", date),
        ], order="date_effet desc, id desc", limit=1)
        if derniere.objet == "postal":
            return "postal", False
        adresse = (partner.sudo().email_notification or "").strip()
        if not adresse:
            return "postal", False
        return "electronique", adresse

    @api.model
    def mention_voie_postale(self):
        """Mention à faire figurer sur les avis d'appel de fonds et les convocations."""
        return MENTION_VOIE_POSTALE

    @api.model
    def demande_en_attente(self, partner):
        """Demande enregistrée mais pas encore en vigueur (ou False)."""
        aujourdhui = fields.Date.context_today(self)
        return self.sudo().search([
            ("personne_id", "=", partner.id),
            ("objet", "in", ("postal", "electronique")),
            ("date_effet", ">", aujourdhui),
        ], order="date_effet desc, id desc", limit=1)
