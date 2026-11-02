"""Page d'accueil de l'extranet : logo du cabinet d'un côté, connexion de l'autre.

- /extranet/connexion affiche la page (accès public) ; un copropriétaire déjà
  connecté est envoyé directement sur son tableau de bord.
- Le formulaire est traité par la connexion standard d'Odoo (/web/login) : en
  cas d'erreur, la même page est réaffichée avec le message.
- Toute demande de connexion vers une page de l'extranet (/extranet…, /my)
  passe par cette page plutôt que par l'écran de connexion d'Odoo.
"""

from urllib.parse import urlencode, urlsplit

from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.session import Session

PAGE_CONNEXION = "coproerp_extranet.page_connexion"
CHEMINS_EXTRANET = ("/extranet", "/my")


def _vers_extranet(redirect):
    """Vrai si la page demandée après connexion fait partie de l'extranet."""
    if not redirect:
        return False
    chemin = urlsplit(redirect).path or ""
    return chemin.startswith(CHEMINS_EXTRANET) and not chemin.startswith("/extranet/connexion")


def _chemin_local(redirect):
    """Ne garde que le chemin (jamais un autre site) : « https://x/extranet/lots?a=1 » → « /extranet/lots?a=1 »."""
    morceaux = urlsplit(redirect)
    return morceaux.path + ("?" + morceaux.query if morceaux.query else "")


def _valeurs_cabinet():
    company = request.env.company.sudo()
    parametres = request.env["ir.config_parameter"].sudo()
    adresse = " – ".join(x for x in (
        company.street, " ".join(y for y in (company.zip, company.city) if y)) if x)
    return {
        "cabinet": company,
        "cabinet_adresse": adresse,
        "reinitialisation": parametres.get_param("auth_signup.reset_password") == "True",
    }


class ExtranetConnexion(Home):

    @http.route(["/extranet/connexion"], type="http", auth="public", sitemap=False)
    def extranet_connexion(self, redirect=None, **kw):
        redirect = _chemin_local(redirect) if _vers_extranet(redirect) else "/extranet"
        if request.session.uid and not request.env.user._is_public():
            return request.redirect(redirect)
        valeurs = dict(_valeurs_cabinet(), redirect=redirect, login=kw.get("login", ""), error=None)
        reponse = request.render(PAGE_CONNEXION, valeurs)
        reponse.headers["X-Frame-Options"] = "SAMEORIGIN"
        reponse.headers["Cache-Control"] = "no-cache"
        return reponse

    @http.route()
    def web_login(self, redirect=None, **kw):
        if (request.httprequest.method == "GET" and _vers_extranet(redirect)
                and not (request.session.uid and not request.env.user._is_public())):
            return request.redirect("/extranet/connexion?" + urlencode({"redirect": _chemin_local(redirect)}))
        reponse = super().web_login(redirect=redirect, **kw)
        # Échec de connexion depuis la page de l'extranet : on y reste, avec le message d'erreur
        if kw.get("extranet_connexion") and getattr(reponse, "template", None) == "web.login":
            reponse.template = PAGE_CONNEXION
            reponse.qcontext.update(_valeurs_cabinet())
            reponse.qcontext["redirect"] = _chemin_local(redirect) if _vers_extranet(redirect) else "/extranet"
        return reponse


class ExtranetDeconnexion(Session):
    """Un copropriétaire qui se déconnecte, quel que soit le lien utilisé (menu de l'extranet ou menu
    de son nom en haut à droite), revient sur la page d'accueil de l'extranet."""

    @http.route()
    def logout(self, redirect="/odoo", **kw):
        # Cette route est publique (auth="none") : l'utilisateur se retrouve à partir de la session.
        uid = request.session.uid
        utilisateur = request.env["res.users"].sudo().browse(uid).exists() if uid else None
        if utilisateur and utilisateur._is_portal():
            redirect = "/extranet/connexion"
        return super().logout(redirect=redirect, **kw)
