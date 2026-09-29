"""Pages de l'extranet des copropriétaires.

Sécurité : chaque page applique deux niveaux de contrôle.
1. Des filtres explicites dans ce contrôleur (personne connectée, copropriété
   sélectionnée, mandat de conseiller syndical en cours).
2. Les règles d'accès de la base (security/extranet_security.xml), qui
   s'appliquent en plus, quoi qu'il arrive, aux utilisateurs du portail.

Les lectures sont faites avec les droits de l'utilisateur connecté. ``sudo()``
n'est utilisé qu'après ces contrôles, pour afficher des noms (gestionnaire,
autres copropriétaires pour le conseil syndical) ou écrire des journaux.
"""

import base64
import logging
from collections import OrderedDict
from odoo import fields, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)

SESSION_COPRO = "coproerp_extranet_copro_id"
RIB_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg")
RIB_TAILLE_MAX = 5 * 1024 * 1024  # 5 Mo


def fmt_eur(montant):
    """1234.5 -> '1 234,50 €' (espace insécable fine)."""
    montant = montant or 0.0
    signe = "-" if montant < 0 else ""
    entier, decimales = f"{abs(montant):.2f}".split(".")
    groupes = []
    while entier:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    return f"{signe}{' '.join(groupes)},{decimales} €"


def fmt_date(valeur):
    return valeur.strftime("%d/%m/%Y") if valeur else ""


def label(record, field_name):
    """Libellé d'une valeur de sélection."""
    if not record:
        return ""
    field = record._fields[field_name]
    return dict(field._description_selection(record.env)).get(record[field_name], "")


class ExtranetPortal(CustomerPortal):

    # ==================================================================
    # Outils
    # ==================================================================
    def _ext_partner(self):
        return request.env.user.partner_id

    def _ext_personnes(self):
        return self._ext_partner()._extranet_personnes()

    def _ext_coproprietes(self):
        """Copropriétés accessibles.

        Portail : les règles d'accès limitent la recherche aux copropriétés
        où la personne a un droit ou un mandat en cours.
        Utilisateur interne (aperçu) : on applique le même filtre explicitement.
        """
        personnes = self._ext_personnes()
        return request.env["coproerp.copropriete"].search(
            [
                ("extranet_actif", "=", True),
                "|",
                ("droit_ids", "any", [
                    ("personne_id", "in", personnes.ids),
                    ("acces_extranet", "=", True),
                ]),
                ("mandat_cs_ids", "any", [
                    ("personne_id", "in", personnes.ids),
                    ("en_cours", "=", True),
                ]),
            ]
        )

    def _ext_copro_courante(self, coproprietes=None):
        coproprietes = coproprietes if coproprietes is not None else self._ext_coproprietes()
        copro_id = request.session.get(SESSION_COPRO)
        copro = coproprietes.filtered(lambda c: c.id == copro_id)
        return copro[:1] or coproprietes[:1]

    def _ext_mandat_cs(self, copro):
        if not copro:
            return request.env["coproerp.cs.mandat"]
        return request.env["coproerp.cs.mandat"].sudo().search(
            [
                ("copropriete_id", "=", copro.id),
                ("personne_id", "in", self._ext_personnes().ids),
                ("en_cours", "=", True),
            ],
            limit=1,
        )

    def _ext_domain_documents(self, copro, est_cs):
        personnes = self._ext_personnes()
        visibilites = [
            "|",
            ("visibilite", "=", "tous"),
            "&",
            ("visibilite", "=", "personnel"),
            ("personne_id", "in", personnes.ids),
        ]
        if est_cs:
            visibilites = ["|", ("visibilite", "=", "conseil_syndical")] + visibilites
        return [("copropriete_id", "=", copro.id), ("publie", "=", True)] + visibilites

    def _ext_documents_non_lus(self, documents):
        lus = request.env["coproerp.extranet.document.lecture"].sudo().search(
            [
                ("document_id", "in", documents.ids),
                ("personne_id", "=", self._ext_partner().id),
            ]
        ).document_id
        return documents - lus

    def _ext_values(self, page, **kw):
        """Valeurs communes à toutes les pages (menu latéral, identité)."""
        coproprietes = self._ext_coproprietes()
        copro = self._ext_copro_courante(coproprietes)
        personnes = self._ext_personnes()
        mandat = self._ext_mandat_cs(copro)
        droits = request.env["coproerp.droit"].sudo().search(
            [
                ("copropriete_id", "=", copro.id),
                ("personne_id", "in", personnes.ids),
                ("acces_extranet", "=", True),
            ]
        ) if copro else request.env["coproerp.droit"]
        qualites = sorted({label(d, "type_droit") for d in droits})
        if mandat:
            qualites.append(
                "Président du conseil syndical" if mandat.fonction == "president"
                else "Membre du conseil syndical"
            )
        nb_non_lus = 0
        if copro:
            docs = request.env["coproerp.extranet.document"].search(
                self._ext_domain_documents(copro, bool(mandat))
            )
            nb_non_lus = len(self._ext_documents_non_lus(docs))
        values = {
            "page_name": "extranet",
            "no_breadcrumbs": True,
            "ext_page": page,
            "partner": self._ext_partner(),
            "coproprietes": coproprietes,
            "copro": copro,
            "copro_sudo": copro.sudo(),
            "mandat_cs": mandat,
            "est_cs": bool(mandat),
            "depenses_visibles": bool(copro) and (
                bool(mandat) or copro.sudo().extranet_depenses_visibilite == "tous"
            ),
            "qualites": qualites,
            "nb_docs_non_lus": nb_non_lus,
            "fmt_eur": fmt_eur,
            "fmt_date": fmt_date,
            "label": label,
            "today": fields.Date.context_today(request.env.user),
        }
        values.update(kw)
        return values

    def _ext_render(self, template, page, **kw):
        values = self._ext_values(page, **kw)
        if not values["copro"]:
            return request.render("coproerp_extranet.page_sans_acces", values)
        return request.render(template, values)

    # ==================================================================
    # Redirection de /my vers l'extranet pour les copropriétaires
    # ==================================================================
    @http.route()
    def home(self, **kw):
        if request.env.user._is_portal() and self._ext_coproprietes():
            return request.redirect("/extranet")
        return super().home(**kw)

    # ==================================================================
    # Tableau de bord
    # ==================================================================
    @http.route(["/extranet"], type="http", auth="user", website=True)
    def extranet_tableau_de_bord(self, **kw):
        values = self._ext_values("tableau")
        copro = values["copro"]
        if not copro:
            return request.render("coproerp_extranet.page_sans_acces", values)

        personnes = self._ext_personnes()
        today = values["today"]
        ecritures = copro._extranet_ecritures(personnes.ids)
        mes_appels = request.env["coproerp.appel.charge"].search(
            [("copropriete_id", "=", copro.id), ("personne_id", "in", personnes.ids)],
            order="date_echeance desc, id desc",
        )
        prochain = mes_appels.filtered(
            lambda a: a.date_echeance and a.date_echeance >= today
        ).sorted("date_echeance")[:1]

        actualites = request.env["coproerp.actualite"].search(
            [
                ("copropriete_id", "=", copro.id),
                ("publie", "=", True),
                ("date_publication", "<=", today),
                "|", ("date_fin", "=", False), ("date_fin", ">=", today),
            ],
            limit=3,
        )
        membres_cs = request.env["coproerp.cs.mandat"].sudo().search(
            [("copropriete_id", "=", copro.id), ("en_cours", "=", True)],
            order="fonction, id",
        )
        values.update(
            {
                "solde": ecritures[-1]["solde"] if ecritures else 0.0,
                "dernier_appel": mes_appels[:1],
                "prochain_appel": prochain,
                "actualites": actualites,
                "membres_cs": membres_cs,
            }
        )
        return request.render("coproerp_extranet.page_tableau_de_bord", values)

    @http.route(["/extranet/copropriete/<int:copro_id>"], type="http", auth="user", website=True)
    def extranet_choisir_copropriete(self, copro_id, redirect="/extranet", **kw):
        if copro_id in self._ext_coproprietes().ids:
            request.session[SESSION_COPRO] = copro_id
        if not redirect.startswith("/extranet"):
            redirect = "/extranet"
        return request.redirect(redirect)

    # ==================================================================
    # Mes lots
    # ==================================================================
    @http.route(["/extranet/lots"], type="http", auth="user", website=True)
    def extranet_lots(self, **kw):
        droits = request.env["coproerp.droit"].search(
            [
                ("personne_id", "in", self._ext_personnes().ids),
                ("acces_extranet", "=", True),
                ("copropriete_id.extranet_actif", "=", True),
            ],
            order="copropriete_id, lot_numero",
        )
        return self._ext_render("coproerp_extranet.page_lots", "lots", droits=droits)

    # ==================================================================
    # Situation comptable
    # ==================================================================
    def _ext_xlsx(self, nom_fichier, titre, entetes, lignes, formats=None):
        """Réponse HTTP contenant un fichier Excel.

        ``formats`` : liste parallèle à ``entetes`` ('texte', 'date', 'montant').
        """
        import io

        import xlsxwriter

        formats = formats or ["texte"] * len(entetes)
        sortie = io.BytesIO()
        classeur = xlsxwriter.Workbook(sortie, {"in_memory": True})
        feuille = classeur.add_worksheet(titre[:31])
        f_titre = classeur.add_format({"bold": True, "font_size": 13})
        f_entete = classeur.add_format({"bold": True, "bg_color": "#DDE6F0", "border": 1})
        f_date = classeur.add_format({"num_format": "dd/mm/yyyy"})
        f_montant = classeur.add_format({"num_format": "#,##0.00 €"})
        feuille.write(0, 0, titre, f_titre)
        for col, entete in enumerate(entetes):
            feuille.write(2, col, entete, f_entete)
            feuille.set_column(col, col, 40 if formats[col] == "texte" else 14)
        for row, ligne in enumerate(lignes, start=3):
            for col, valeur in enumerate(ligne):
                if valeur in (None, False):
                    continue
                if formats[col] == "date":
                    feuille.write_datetime(
                        row, col, fields.Datetime.to_datetime(valeur), f_date
                    )
                elif formats[col] == "montant":
                    feuille.write_number(row, col, valeur, f_montant)
                else:
                    feuille.write(row, col, valeur)
        classeur.close()
        contenu = sortie.getvalue()
        return request.make_response(
            contenu,
            headers=[
                ("Content-Type",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", http.content_disposition(nom_fichier)),
                ("Content-Length", len(contenu)),
            ],
        )

    def _ext_page_situation(self, values, personne, export=None, retour=False):
        copro = values["copro"]
        ecritures = copro._extranet_ecritures(personne.ids)
        solde = ecritures[-1]["solde"] if ecritures else 0.0
        if export == "xlsx":
            return self._ext_xlsx(
                "situation_%s.xlsx" % (copro.reference or copro.id),
                "Situation comptable - %s" % personne.name,
                ["Date comptable", "Libellé écriture", "Débit", "Crédit", "Solde"],
                [[e["date"], e["libelle"], e["debit"] or None, e["credit"] or None, e["solde"]]
                 for e in ecritures],
                ["date", "texte", "montant", "montant", "montant"],
            )
        values.update(
            {
                "ecritures": list(reversed(ecritures)),
                "solde": solde,
                "total_debit": sum(e["debit"] for e in ecritures),
                "total_credit": sum(e["credit"] for e in ecritures),
                "personne_nom": personne.sudo().name,
                "retour": retour,
                "export_url": request.httprequest.path + "?export=xlsx",
            }
        )
        return request.render("coproerp_extranet.page_situation", values)

    @http.route(["/extranet/situation"], type="http", auth="user", website=True)
    def extranet_situation(self, export=None, **kw):
        values = self._ext_values("situation")
        if not values["copro"]:
            return request.render("coproerp_extranet.page_sans_acces", values)
        return self._ext_page_situation(values, self._ext_personnes(), export=export)

    @http.route(["/extranet/appels/<int:appel_id>"], type="http", auth="user", website=True)
    def extranet_appel_detail(self, appel_id, **kw):
        values = self._ext_values("situation")
        copro = values["copro"]
        if not copro:
            return request.render("coproerp_extranet.page_sans_acces", values)
        domain = [("id", "=", appel_id), ("copropriete_id", "=", copro.id)]
        if not values["est_cs"]:
            domain.append(("personne_id", "in", self._ext_personnes().ids))
        appel = request.env["coproerp.appel.charge"].search(domain, limit=1)
        if not appel:
            raise request.not_found()
        documents = request.env["coproerp.extranet.document"].search(
            [("appel_id", "=", appel.id)]
            + self._ext_domain_documents(copro, values["est_cs"])
        )
        values.update(
            {
                "appel": appel,
                "personne_nom": appel.sudo().personne_id.name,
                "documents": documents,
            }
        )
        return request.render("coproerp_extranet.page_appel_detail", values)

    # ---- Réservé au conseil syndical --------------------------------
    @http.route(["/extranet/situation/coproprietaires"], type="http", auth="user", website=True)
    def extranet_situation_coproprietaires(self, export=None, **kw):
        values = self._ext_values("coproprietaires")
        if not (values["copro"] and values["est_cs"]):
            return request.redirect("/extranet")
        copro = values["copro"]
        # Les montants sont lus avec les droits de l'utilisateur : la règle
        # « conseil syndical » de la base s'applique en plus de ce contrôle.
        lignes = copro._extranet_soldes_coproprietaires()
        if export == "xlsx":
            return self._ext_xlsx(
                "soldes_coproprietaires_%s.xlsx" % (copro.reference or copro.id),
                "Solde par copropriétaire - %s" % copro.name,
                ["N° d'immeuble", "N° de copropriétaire", "Copropriétaire", "Lots", "Solde"],
                [[copro.reference or "", l["numero"], l["nom"], l["lots"], l["solde"]]
                 for l in lignes],
                ["texte", "texte", "texte", "texte", "montant"],
            )
        values.update(
            {
                "lignes": lignes,
                "total_soldes": sum(l["solde"] for l in lignes),
                "export_url": request.httprequest.path + "?export=xlsx",
            }
        )
        return request.render("coproerp_extranet.page_coproprietaires", values)

    @http.route(
        ["/extranet/situation/coproprietaire/<int:partner_id>"],
        type="http", auth="user", website=True,
    )
    def extranet_situation_coproprietaire(self, partner_id, export=None, **kw):
        values = self._ext_values("coproprietaires")
        if not (values["copro"] and values["est_cs"]):
            return request.redirect("/extranet")
        personne = request.env["res.partner"].sudo().browse(partner_id).exists()
        if not personne:
            raise request.not_found()
        return self._ext_page_situation(
            values, personne.with_env(request.env), export=export,
            retour="/extranet/situation/coproprietaires",
        )

    @http.route(["/extranet/situation/depenses"], type="http", auth="user", website=True)
    def extranet_situation_depenses(self, export=None, **kw):
        values = self._ext_values("depenses")
        copro = values["copro"]
        if not (copro and values["depenses_visibles"]):
            return request.redirect("/extranet")
        depenses = copro._extranet_depenses()
        if export == "xlsx":
            return self._ext_xlsx(
                "depenses_%s.xlsx" % (copro.reference or copro.id),
                "Relevé général des dépenses - %s" % copro.name,
                ["Compte", "Libellé compte", "Date comptable", "Libellé écriture", "Débit", "Crédit"],
                [[d["compte"], d["libelle_compte"], d["date"], d["libelle"],
                  d["debit"] or None, d["credit"] or None] for d in depenses],
                ["texte", "texte", "date", "texte", "montant", "montant"],
            )
        values.update(
            {
                "depenses": depenses,
                "export_url": request.httprequest.path + "?export=xlsx",
            }
        )
        return request.render("coproerp_extranet.page_depenses", values)

    # ==================================================================
    # Documents
    # ==================================================================
    @http.route(["/extranet/documents"], type="http", auth="user", website=True)
    def extranet_documents(self, **kw):
        values = self._ext_values("documents")
        copro = values["copro"]
        if not copro:
            return request.render("coproerp_extranet.page_sans_acces", values)
        documents = request.env["coproerp.extranet.document"].search(
            self._ext_domain_documents(copro, values["est_cs"]),
            order="date_document desc, id desc",
        )
        non_lus = self._ext_documents_non_lus(documents)
        par_categorie = OrderedDict()
        for doc in documents.sorted(lambda d: (d.categorie_id.sequence, d.categorie_id.name or "")):
            par_categorie.setdefault(doc.categorie_id, request.env["coproerp.extranet.document"])
            par_categorie[doc.categorie_id] |= doc
        # Tri par date à l'intérieur de chaque catégorie
        for cat, docs in par_categorie.items():
            par_categorie[cat] = docs.sorted(lambda d: (d.date_document, d.id), reverse=True)
        values.update({"par_categorie": par_categorie, "non_lus": non_lus})
        return request.render("coproerp_extranet.page_documents", values)

    @http.route(
        ["/extranet/documents/<int:document_id>/telecharger"],
        type="http", auth="user", website=True,
    )
    def extranet_document_telecharger(self, document_id, **kw):
        coproprietes = self._ext_coproprietes()
        copro = self._ext_copro_courante(coproprietes)
        if not copro:
            raise request.not_found()
        mandat = self._ext_mandat_cs(copro)
        doc = request.env["coproerp.extranet.document"].search(
            [("id", "=", document_id)] + self._ext_domain_documents(copro, bool(mandat)),
            limit=1,
        )
        if not doc:
            raise request.not_found()
        try:
            doc.check_access("read")
        except (AccessError, MissingError):
            raise request.not_found()
        doc._marquer_lu(self._ext_partner())
        stream = request.env["ir.binary"]._get_stream_from(
            doc.sudo(), "fichier", filename=doc.nom_fichier or doc.name
        )
        return stream.get_response(as_attachment=True)

    # ==================================================================
    # Dématérialisation
    # ==================================================================
    @http.route(["/extranet/dematerialisation"], type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def extranet_dematerialisation(self, **post):
        partner = self._ext_partner()
        Consentement = request.env["coproerp.demat.consentement"]
        types = dict(Consentement._fields["type_envoi"]._description_selection(request.env))
        message = False
        if request.httprequest.method == "POST" and self._ext_coproprietes():
            type_envoi = post.get("type_envoi")
            accord = post.get("accord") == "1"
            if type_envoi in types:
                if accord and not post.get("confirmation"):
                    message = ("danger", "Merci de cocher la case de confirmation pour donner votre accord.")
                elif accord and not partner.email:
                    message = ("danger", "Renseignez d'abord votre adresse e-mail dans « Mon compte ».")
                else:
                    Consentement.sudo().create(
                        {
                            "personne_id": partner.id,
                            "type_envoi": type_envoi,
                            "accord": accord,
                            "origine": "extranet",
                            "adresse_ip": request.httprequest.remote_addr,
                            "user_agent": (request.httprequest.user_agent.string or "")[:250],
                            "email": partner.email,
                            "utilisateur_id": request.env.user.id,
                        }
                    )
                    message = ("success", "Votre choix a bien été enregistré.")
        etat = Consentement.etat_actuel(partner)
        historique = Consentement.search([("personne_id", "=", partner.id)], limit=20)
        return self._ext_render(
            "coproerp_extranet.page_dematerialisation", "demat",
            types=types, etat=etat, historique=historique, message=message,
        )

    # ==================================================================
    # Actualités
    # ==================================================================
    @http.route(["/extranet/actualites"], type="http", auth="user", website=True)
    def extranet_actualites(self, **kw):
        values = self._ext_values("actualites")
        copro = values["copro"]
        if not copro:
            return request.render("coproerp_extranet.page_sans_acces", values)
        today = values["today"]
        values["actualites"] = request.env["coproerp.actualite"].search(
            [
                ("copropriete_id", "=", copro.id),
                ("publie", "=", True),
                ("date_publication", "<=", today),
                "|", ("date_fin", "=", False), ("date_fin", ">=", today),
            ]
        )
        return request.render("coproerp_extranet.page_actualites", values)

    # ==================================================================
    # Modes de règlement
    # ==================================================================
    @http.route(["/extranet/reglement"], type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def extranet_reglement(self, **post):
        values = self._ext_values("reglement")
        copro = values["copro"]
        if not copro:
            return request.render("coproerp_extranet.page_sans_acces", values)
        partner = self._ext_partner()
        message = False
        if request.httprequest.method == "POST":
            fichier = request.httprequest.files.get("rib")
            if not fichier or not fichier.filename:
                message = ("danger", "Veuillez choisir un fichier.")
            elif not fichier.filename.lower().endswith(RIB_EXTENSIONS):
                message = ("danger", "Formats acceptés : PDF, PNG ou JPG.")
            else:
                contenu = fichier.read(RIB_TAILLE_MAX + 1)
                if len(contenu) > RIB_TAILLE_MAX:
                    message = ("danger", "Le fichier dépasse 5 Mo.")
                else:
                    demande = request.env["coproerp.rib.demande"].sudo().create(
                        {
                            "personne_id": partner.id,
                            "copropriete_id": copro.id,
                            "fichier": base64.b64encode(contenu),
                            "nom_fichier": fichier.filename,
                        }
                    )
                    gestionnaire = copro.sudo().gestionnaire_id
                    if gestionnaire:
                        demande.message_subscribe(partner_ids=gestionnaire.partner_id.ids)
                        demande.message_post(
                            body="Nouveau RIB déposé sur l'extranet : demande de mandat SEPA.",
                            partner_ids=gestionnaire.partner_id.ids,
                            subtype_xmlid="mail.mt_comment",
                        )
                    message = (
                        "success",
                        "Votre RIB a bien été transmis. Votre gestionnaire vous fera "
                        "parvenir un mandat de prélèvement SEPA.",
                    )
        values["demandes"] = request.env["coproerp.rib.demande"].search(
            [("personne_id", "=", partner.id)]
        )
        values["message"] = message
        return request.render("coproerp_extranet.page_reglement", values)

    # ==================================================================
    # Mon compte
    # ==================================================================
    @http.route(["/extranet/compte"], type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def extranet_compte(self, **post):
        partner = self._ext_partner()
        message = False
        if request.httprequest.method == "POST":
            partner.sudo().extranet_notif_documents = bool(post.get("notif_documents"))
            message = ("success", "Vos préférences ont été enregistrées.")
        return self._ext_render(
            "coproerp_extranet.page_compte", "compte", message=message
        )
