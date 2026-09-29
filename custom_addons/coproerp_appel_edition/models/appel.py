import base64
from collections import OrderedDict

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round

LIBELLES_TRIMESTRE = {1: "1er", 2: "2e", 3: "3e", 4: "4e"}


class AppelCharge(models.Model):
    _inherit = "coproerp.appel.charge"

    budget_origine_id = fields.Many2one(
        "coproerp.budget.annuel",
        string="Budget d'origine",
        ondelete="restrict",
        index=True,
        help="Budget dont est issu un appel du budget courant.",
    )
    echeance_travaux_id = fields.Many2one(
        "coproerp.travaux.echeance",
        string="Échéance travaux",
        ondelete="restrict",
        index=True,
    )
    libelle_echeance = fields.Char(
        string="Échéance (libellé)", compute="_compute_libelle_echeance"
    )

    @api.depends("date_debut_periode", "date_fin_periode", "date_echeance")
    def _compute_libelle_echeance(self):
        for appel in self:
            debut, fin = appel.date_debut_periode, appel.date_fin_periode
            if (
                debut and fin and debut.day == 1 and debut.month in (1, 4, 7, 10)
                and (fin.month - debut.month) == 2 and fin.year == debut.year
            ):
                trimestre = (debut.month - 1) // 3 + 1
                appel.libelle_echeance = "%s trimestre %s" % (LIBELLES_TRIMESTRE[trimestre], debut.year)
            elif debut and fin:
                appel.libelle_echeance = "du %s au %s" % (
                    debut.strftime("%d/%m/%Y"), fin.strftime("%d/%m/%Y"))
            elif appel.date_echeance:
                appel.libelle_echeance = "échéance du %s" % appel.date_echeance.strftime("%d/%m/%Y")
            else:
                appel.libelle_echeance = ""

    # ------------------------------------------------------------------
    # Avis d'appel : regroupement par copropriétaire et par échéance
    # ------------------------------------------------------------------
    def avis_regroupes(self):
        """Regroupe les appels à imprimer : un avis par (copropriété,
        destinataire, date d'échéance). Utilisé par le modèle d'impression."""
        ordre_types = {"budget_courant": 1, "fonds_travaux": 2, "appel_exceptionnel": 3}
        groupes = OrderedDict()
        for appel in self.sorted(lambda a: (
            a.copropriete_id.name or "", (a.personne_id.name or "").lower(),
            a.date_echeance, ordre_types.get(a.type_appel, 9), a.id,
        )):
            cle = (appel.copropriete_id.id, appel.personne_id.id, appel.date_echeance)
            groupes.setdefault(cle, self.browse())
            groupes[cle] |= appel
        avis = []
        for appels in groupes.values():
            premier = appels[0]
            lots = appels.groupe_ids.lot_id.sorted(lambda l: l.numero or "")
            avis.append({
                "appels": appels,
                "copro": premier.copropriete_id,
                "personne": premier.personne_id,
                "date_edition": min(appels.mapped("date_appel")),
                "date_echeance": premier.date_echeance,
                "libelle_echeance": premier.libelle_echeance,
                "lots": lots,
                "total": float_round(sum(appels.mapped("total_appel")), precision_digits=2),
                # Complétés par le module de comptabilité s'il est installé
                "projet": False,
                "releve": False,
                "fonds": False,
                "reference": "%s %s %s" % (
                    premier.copropriete_id.reference or premier.copropriete_id.id,
                    premier.personne_id.ref or str(premier.personne_id.id).zfill(7),
                    premier.reference or "",
                ),
            })
        for a in avis:
            a["a_regler"] = a["total"]
        return avis

    @api.model
    def titre_section(self, appel):
        if appel.type_appel == "budget_courant":
            return "BUDGET COURANT"
        if appel.type_appel == "fonds_travaux":
            return "FONDS OBLIGATOIRE TRAVAUX"
        if appel.type_appel == "appel_exceptionnel" and appel.travaux_id:
            return ("TRAVAUX : %s" % (appel.travaux_id.name or "")).upper()
        return dict(self._fields["type_appel"]._description_selection(self.env)).get(
            appel.type_appel, "").upper()

    # ------------------------------------------------------------------
    # Publication sur l'extranet (document personnel du copropriétaire)
    # ------------------------------------------------------------------
    def action_publier_avis_extranet(self):
        rapport = self.env.ref("coproerp_appel_edition.action_report_avis_appel")
        categorie = self.env.ref("coproerp_extranet.categorie_appels_fonds")
        Document = self.env["coproerp.extranet.document"]
        publies = 0
        for avis in self.avis_regroupes():
            appels = avis["appels"]
            if Document.search_count([("appel_id", "in", appels.ids)]):
                continue  # déjà publié
            pdf, _type = rapport._render_qweb_pdf(rapport.report_name, appels.ids)
            nom = "Appel de fonds %s - %s.pdf" % (
                avis["libelle_echeance"], avis["personne"].name)
            document = Document.create({
                "name": "Appel de fonds — %s" % avis["libelle_echeance"],
                "copropriete_id": avis["copro"].id,
                "categorie_id": categorie.id,
                "visibilite": "personnel",
                "personne_id": avis["personne"].id,
                "appel_id": appels[0].id,
                "fichier": base64.b64encode(pdf),
                "nom_fichier": nom,
                "date_document": avis["date_edition"],
            })
            document.action_publier()
            publies += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Publication sur l'extranet",
                "message": "%s avis publié(s) ; les avis déjà publiés ont été ignorés." % publies,
                "type": "success",
            },
        }


class AppelChargePoste(models.Model):
    _inherit = "coproerp.appel.charge.poste"

    # Montant arrondi au centime, ligne par ligne, comme sur l'avis.
    @api.depends("total_a_repartir", "nombre_parts_lot", "nombre_total_parts")
    def _compute_montant_appel(self):
        for poste in self:
            if poste.nombre_total_parts:
                poste.montant_appel = float_round(
                    poste.total_a_repartir * poste.nombre_parts_lot / poste.nombre_total_parts,
                    precision_digits=2,
                )
            else:
                poste.montant_appel = 0.0

    # Les postes issus d'un échéancier de travaux gardent leur propre montant
    # (pourcentage de l'échéance, honoraires) : la règle d'origine, qui impose
    # le « montant par appel » du financement, ne s'applique pas à eux.
    def _get_financement_exceptionnel(self):
        financement = super()._get_financement_exceptionnel()
        if financement and (financement.echeance_ids or self.appel_id.echeance_travaux_id):
            return financement.browse()
        return financement

    # Le fonds travaux et les travaux peuvent être appelés selon n'importe
    # quelle clé (ex. : charges communes générales), ce que refusait le
    # contrôle d'origine. Les autres contrôles sont conservés.
    @api.constrains("repartition_id", "type_poste", "copropriete_id")
    def _check_type_repartition(self):
        for poste in self:
            if (
                poste.repartition_id and poste.copropriete_id
                and poste.repartition_id.copropriete_id != poste.copropriete_id
            ):
                raise ValidationError(
                    "La clé de répartition doit appartenir à la même copropriété que le poste."
                )
            if poste.type_poste in ("fonds_travaux", "travaux_exceptionnels"):
                continue
            if (
                poste.repartition_id and poste.type_poste
                and poste.type_poste != poste.repartition_id.type_repartition
                and "autre" not in (poste.type_poste, poste.repartition_id.type_repartition)
            ):
                raise ValidationError(
                    "Le type du poste de dépense doit correspondre au type de la clé de répartition."
                )
