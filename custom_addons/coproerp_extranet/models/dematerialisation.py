from odoo import api, fields, models
from odoo.exceptions import UserError

TYPES_ENVOI = [
    ("convocation_ag", "Convocation d'assemblée générale"),
    ("pv_ag", "Notification du procès-verbal d'assemblée générale"),
    ("appel_fonds", "Appels de fonds et relances"),
]


class DematerialisationConsentement(models.Model):
    """Journal (non modifiable) des accords et retraits d'accord à la
    notification électronique.

    L'état en vigueur pour une personne et un type d'envoi est la dernière
    ligne du journal. Chaque ligne conserve la date, l'origine et l'adresse IP,
    pour pouvoir justifier de l'accord exprès du copropriétaire
    (art. 42-1 de la loi du 10 juillet 1965, art. 64-1 et s. du décret du
    17 mars 1967).
    """

    _name = "coproerp.demat.consentement"
    _description = "Accord à la notification électronique"
    _order = "date desc, id desc"

    personne_id = fields.Many2one(
        "res.partner",
        string="Copropriétaire",
        required=True,
        ondelete="cascade",
        index=True,
    )
    type_envoi = fields.Selection(TYPES_ENVOI, string="Type d'envoi", required=True)
    accord = fields.Boolean(string="Accord")
    date = fields.Datetime(
        string="Date", default=fields.Datetime.now, required=True, readonly=True
    )
    origine = fields.Selection(
        [
            ("extranet", "Extranet (par le copropriétaire)"),
            ("syndic", "Saisie par le syndic"),
            ("ag", "Assemblée générale"),
            ("courrier", "Courrier"),
        ],
        string="Origine",
        required=True,
        default="syndic",
    )
    adresse_ip = fields.Char(string="Adresse IP", readonly=True)
    user_agent = fields.Char(string="Navigateur", readonly=True)
    utilisateur_id = fields.Many2one(
        "res.users",
        string="Enregistré par",
        default=lambda self: self.env.user,
        readonly=True,
    )
    email = fields.Char(string="Adresse électronique au moment de l'accord")

    def write(self, vals):
        # Journal de preuve : aucune modification a posteriori.
        raise UserError(
            "Le journal des accords ne peut pas être modifié. "
            "Enregistrez un nouvel accord ou un retrait."
        )

    @api.model
    def etat_actuel(self, partner):
        """Retourne {type_envoi: (accord, date)} pour ``partner``."""
        etat = {}
        lignes = self.sudo().search(
            [("personne_id", "=", partner.id)], order="date desc, id desc"
        )
        for ligne in lignes:
            if ligne.type_envoi not in etat:
                etat[ligne.type_envoi] = (ligne.accord, ligne.date)
        return etat
