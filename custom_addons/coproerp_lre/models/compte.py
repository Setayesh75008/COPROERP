from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import ar24

URL_BAC_A_SABLE = "https://sandbox.ar24.fr/api/"


class CompteLre(models.Model):
    """Compte du syndic chez AR24, prestataire de lettre recommandée électronique qualifiée."""

    _name = "coproerp.lre.compte"
    _description = "Compte AR24 (lettre recommandée électronique)"

    name = fields.Char(string="Libellé", required=True, default="AR24")
    active = fields.Boolean(default=True)
    url_api = fields.Char(
        string="Adresse de l'API", required=True, default=URL_BAC_A_SABLE,
        help="Plateforme de test (bac à sable) par défaut : https://sandbox.ar24.fr/api/. Pour les envois réels, "
             "indiquez l'adresse de production communiquée par AR24 avec vos accès.")
    token = fields.Char(string="Token API", required=True, groups="base.group_system")
    cle_privee = fields.Char(string="Clé privée", required=True, groups="base.group_system")
    id_user = fields.Char(
        string="Identifiant AR24 de l'expéditeur (id_user)", required=True,
        help="Compte AR24 du syndic qui expédie les lettres (compte confirmé, conditions acceptées, moyen de "
             "paiement enregistré).")
    eidas = fields.Boolean(
        string="LRE qualifiée eIDAS", default=True,
        help="La lettre recommandée électronique doit être qualifiée (art. L. 100 du code des postes et des "
             "communications électroniques) pour valoir lettre recommandée avec accusé de réception. Sans "
             "authentification de l'expéditeur par code, AR24 met chaque lettre « à valider » : validez-les "
             "depuis votre espace AR24 dans les 7 jours.")
    nom_expediteur = fields.Char(string="Complément du nom de l'expéditeur",
                                 help="Ajouté au nom de l'expéditeur affiché au destinataire (ex. : nom du cabinet).")
    bac_a_sable = fields.Boolean(string="Plateforme de test", compute="_compute_bac_a_sable")

    @api.depends("url_api")
    def _compute_bac_a_sable(self):
        for compte in self:
            compte.bac_a_sable = "sandbox" in (compte.url_api or "")

    @api.model
    def compte_actif(self):
        compte = self.sudo().search([("active", "=", True)], limit=1)
        if not compte:
            raise UserError("Aucun compte AR24 n'est paramétré (menu Lettres recommandées électroniques → "
                            "Compte AR24).")
        return compte

    # ------------------------------------------------------------------
    def _date_requete(self):
        return datetime.now(pytz.timezone("Europe/Paris")).strftime("%Y-%m-%d %H:%M:%S")

    def _appel(self, methode, chemin, donnees=None, fichiers=None):
        """Appel de l'API ; retourne le contenu de « result ». Lève UserError en cas d'erreur."""
        self.ensure_one()
        import requests

        compte = self.sudo()
        date = self._date_requete()
        parametres = dict(donnees or {}, token=compte.token, date=date)
        url = compte.url_api.rstrip("/") + "/" + chemin.lstrip("/")
        entetes = {"signature": ar24.signature(date, compte.cle_privee)}
        try:
            if methode == "GET":
                reponse = requests.get(url, params=parametres, headers=entetes, timeout=60)
            else:
                reponse = requests.post(url, data=parametres, files=fichiers, headers=entetes, timeout=60)
        except requests.RequestException as erreur:
            raise UserError("AR24 ne répond pas : %s" % erreur) from None
        try:
            contenu = ar24.lire_reponse(reponse.text, date, compte.cle_privee)
        except ValueError as erreur:
            raise UserError(str(erreur)) from None
        return self._resultat(contenu)

    @api.model
    def _resultat(self, contenu):
        statut = str(contenu.get("status", "")).upper()
        if statut == "MAINTENANCE":
            raise UserError("AR24 est en maintenance : réessayez plus tard.")
        if statut != "SUCCESS":
            message = contenu.get("message") or contenu.get("slug") or contenu
            raise UserError("AR24 a refusé la demande : %s" % message)
        return contenu.get("result") or {}

    def action_tester(self):
        self.ensure_one()
        resultat = self._appel("GET", "user", {"id_user": self.id_user})
        nom = " ".join(x for x in (resultat.get("firstname"), resultat.get("lastname")) if x) or resultat.get("email")
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": "Connexion à AR24 réussie", "type": "success", "sticky": False,
                       "message": "Expéditeur : %s%s" % (nom or self.id_user,
                                                          " (plateforme de test)" if self.bac_a_sable else "")},
        }
