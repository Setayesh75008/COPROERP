import base64
import logging
from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ETATS = [
    ("brouillon", "À envoyer"),
    ("a_valider", "À valider sur AR24"),
    ("envoye", "Déposée – en attente"),
    ("recu", "Acceptée par le destinataire"),
    ("refuse", "Refusée"),
    ("negligence", "Non réclamée (15 jours)"),
    ("rebond", "Adresse invalide"),
    ("erreur", "Erreur"),
]
ETATS_EN_COURS = ("a_valider", "envoye")


def date_ar24(valeur):
    """« 2026-10-31 09:15:00 » (heure de Paris) → datetime UTC naïf (stockage Odoo)."""
    if not valeur or str(valeur).startswith("0000"):
        return False
    try:
        locale = datetime.strptime(str(valeur)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return pytz.timezone("Europe/Paris").localize(locale).astimezone(pytz.utc).replace(tzinfo=None)


def nom_prenom(nom):
    """« DUPONT Marie » → ("DUPONT", "Marie") : les mots en capitales forment le nom de famille."""
    mots = (nom or "").split()
    capitales = [m for m in mots if m.isupper() and len(m) > 1]
    autres = [m for m in mots if m not in capitales]
    if capitales and autres:
        return " ".join(capitales), " ".join(autres)
    if len(mots) >= 2:
        return " ".join(mots[1:]), mots[0]
    return nom or "", ""


class EnvoiLre(models.Model):
    """Une lettre recommandée électronique adressée par AR24 (une par destinataire)."""

    _name = "coproerp.lre.envoi"
    _description = "Lettre recommandée électronique"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(string="Objet", required=True)
    copropriete_id = fields.Many2one("coproerp.copropriete", string="Copropriété", index=True)
    personne_id = fields.Many2one("res.partner", string="Destinataire", required=True)
    email = fields.Char(string="Adresse électronique", required=True)
    professionnel = fields.Boolean(string="Destinataire professionnel (société)")
    nom = fields.Char(string="Nom")
    prenom = fields.Char(string="Prénom")
    societe = fields.Char(string="Société")
    contenu = fields.Html(string="Message", sanitize=True)
    document = fields.Binary(string="Lettre (PDF)", attachment=True, required=True)
    document_nom = fields.Char(string="Nom du fichier")
    res_model = fields.Char(string="Document d'origine (modèle)", readonly=True)
    res_id = fields.Integer(string="Document d'origine (id)", readonly=True)
    etat = fields.Selection(ETATS, string="État", default="brouillon", required=True, readonly=True, tracking=True)
    ar24_id = fields.Char(string="N° AR24", readonly=True, copy=False, index=True)
    ar24_piece_id = fields.Char(string="Pièce jointe AR24", readonly=True, copy=False)
    statut_ar24 = fields.Char(string="Statut AR24", readonly=True)
    date_depot = fields.Datetime(string="Déposée / destinataire avisé le", readonly=True,
                                 help="Date de la preuve de dépôt : AR24 avise alors le destinataire par courriel.")
    date_reception = fields.Datetime(string="Acceptée le", readonly=True)
    date_refus = fields.Datetime(string="Refusée le", readonly=True)
    date_negligence = fields.Datetime(string="Non réclamée constatée le", readonly=True)
    preuve_depot_url = fields.Char(string="Preuve de dépôt", readonly=True)
    preuve_reception_url = fields.Char(string="Preuve de réception", readonly=True)
    preuve_refus_url = fields.Char(string="Preuve de refus", readonly=True)
    preuve_negligence_url = fields.Char(string="Preuve de non-réclamation", readonly=True)
    erreur = fields.Text(string="Erreur", readonly=True)

    # ------------------------------------------------------------------
    @api.model
    def preparer(self, origine, copro, personne, email, objet, pdf, nom_fichier, contenu=None):
        """Crée l'envoi (sans l'expédier) pour un document d'origine."""
        nom, prenom = nom_prenom(personne.name)
        return self.create({
            "name": objet, "copropriete_id": copro.id,
            "personne_id": personne.id, "email": (email or "").strip(), "professionnel": personne.is_company,
            "nom": nom, "prenom": prenom, "societe": personne.name if personne.is_company else False,
            "contenu": contenu or self._contenu_par_defaut(objet, copro),
            "document": base64.b64encode(pdf), "document_nom": nom_fichier,
            "res_model": origine._name, "res_id": origine.id,
        })

    @api.model
    def _contenu_par_defaut(self, objet, copro):
        syndic = copro.syndic_id.name if copro and copro.syndic_id else ""
        return ("<p>Madame, Monsieur,</p><p>Veuillez trouver ci-joint : %s%s.</p>"
                "<p>Cette lettre recommandée électronique vous est adressée en application de l'article 42-1 de la "
                "loi n° 65-557 du 10 juillet 1965.</p><p>%s</p>") % (
            objet, " – %s" % copro.name if copro else "", ("Le syndic, %s" % syndic) if syndic else "")

    def origine(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return None
        record = self.env[self.res_model].browse(self.res_id).exists()
        return record or None

    def action_envoyer(self):
        compte = self.env["coproerp.lre.compte"].compte_actif()
        for envoi in self.filtered(lambda e: e.etat in ("brouillon", "erreur")):
            try:
                envoi._expedier(compte)
            except UserError as erreur:
                envoi.write({"etat": "erreur", "erreur": str(erreur)})
                envoi.message_post(body="Échec de l'envoi : %s" % erreur)
        return True

    def _expedier(self, compte):
        self.ensure_one()
        if not self.email or "@" not in self.email:
            raise UserError("Adresse électronique du destinataire manquante ou invalide.")
        if not self.ar24_piece_id:
            piece = compte._appel("POST", "attachment", {"id_user": compte.id_user, "file_name": self.document_nom},
                                  fichiers={"file": (self.document_nom, base64.b64decode(self.document),
                                                     "application/pdf")})
            self.ar24_piece_id = str(piece.get("file_id") or "")
            if not self.ar24_piece_id:
                raise UserError("AR24 n'a pas renvoyé d'identifiant pour la pièce jointe.")
        donnees = {
            "id_user": compte.id_user, "to_email": self.email,
            "dest_statut": "professionnel" if self.professionnel else "particulier",
            "to_lastname": self.nom or self.personne_id.name, "to_firstname": self.prenom or "",
            "eidas": "1" if compte.eidas else "0", "content": self.contenu or "",
            "attachment[0]": self.ar24_piece_id,
            "ref_dossier": (self.copropriete_id.reference or self.copropriete_id.name or "")[:50]
            if self.copropriete_id else "",
            "ref_client": (self.personne_id.ref or "")[:50],
        }
        if self.professionnel:
            donnees["to_company"] = self.societe or self.personne_id.name
        if compte.nom_expediteur:
            donnees["custom_name_sender"] = compte.nom_expediteur
        resultat = compte._appel("POST", "mail", donnees)
        self.write({"ar24_id": str(resultat.get("id") or ""), "erreur": False})
        self._maj(resultat)
        self.message_post(body="Lettre transmise à AR24 (n° %s)." % self.ar24_id)

    def action_actualiser(self):
        compte = self.env["coproerp.lre.compte"].compte_actif()
        for envoi in self.filtered("ar24_id"):
            try:
                envoi._maj(compte._appel("GET", "mail", {"id": envoi.ar24_id}))
            except UserError as erreur:
                _logger.warning("LRE %s : %s", envoi.ar24_id, erreur)
                envoi.erreur = str(erreur)
        return True

    def _maj(self, resultat):
        """Met à jour l'envoi d'après la fiche AR24 de la lettre, puis le document d'origine."""
        self.ensure_one()
        vals = {"statut_ar24": resultat.get("status") or self.statut_ar24}
        for champ, cles in (
            ("date_depot", ("ts_ev_date", "ts_dp_date")), ("date_reception", ("view_date",)),
            ("date_refus", ("refused_date",)), ("date_negligence", ("negligence_date",)),
        ):
            for cle in cles:
                valeur = date_ar24(resultat.get(cle))
                if valeur:
                    vals[champ] = valeur
                    break
        for champ, cles in (
            ("preuve_depot_url", ("proof_ev_url", "proof_dp_url")), ("preuve_reception_url", ("proof_ar_url",)),
            ("preuve_refus_url", ("proof_rf_url",)), ("preuve_negligence_url", ("proof_ng_url",)),
        ):
            for cle in cles:
                if resultat.get(cle):
                    vals[champ] = resultat[cle]
                    break
        statut = (resultat.get("status") or "").lower()
        if vals.get("date_refus") or statut in ("refused", "rf"):
            vals["etat"] = "refuse"
        elif vals.get("date_negligence") or statut in ("negligence", "ng"):
            vals["etat"] = "negligence"
        elif resultat.get("ts_bc_date") or resultat.get("bounce_code") or statut in ("bounce", "bc"):
            vals["etat"] = "rebond"
            vals["erreur"] = "Adresse invalide : %s" % (resultat.get("bounce_message") or resultat.get("bounce_code") or "")
        elif vals.get("date_reception") or statut in ("ar", "view"):
            vals["etat"] = "recu"
        elif statut == "to_valid":
            vals["etat"] = "a_valider"
        elif statut in ("not_sent",) or resultat.get("send_fail"):
            vals["etat"] = "erreur"
            vals["erreur"] = "AR24 n'a pas pu envoyer la lettre."
        else:
            vals["etat"] = "envoye"
        self.write(vals)
        origine = self.origine()
        if origine is not None and hasattr(origine, "_lre_mise_a_jour"):
            origine._lre_mise_a_jour(self)

    @api.model
    def _cron_actualiser(self):
        envois = self.search([("etat", "in", ETATS_EN_COURS), ("ar24_id", "!=", False)], limit=200)
        if envois and self.env["coproerp.lre.compte"].sudo().search_count([("active", "=", True)]):
            envois.action_actualiser()

    def action_ouvrir_origine(self):
        self.ensure_one()
        origine = self.origine()
        if origine is None:
            raise UserError("Le document d'origine n'existe plus.")
        return {"type": "ir.actions.act_window", "res_model": origine._name, "res_id": origine.id, "view_mode": "form"}

    def date_locale(self, valeur):
        """Datetime UTC → date à Paris."""
        if not valeur:
            return False
        return pytz.utc.localize(valeur).astimezone(pytz.timezone("Europe/Paris")).date()
