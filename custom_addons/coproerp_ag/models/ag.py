from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Délai de convocation : 21 jours (art. 9 du décret du 17 mars 1967), courant à
# compter du lendemain de la première présentation (art. 64) : l'assemblée se
# tient au plus tôt le 22e jour qui suit la première présentation.
DELAI_CONVOCATION = 21
# Vote par correspondance : formulaire reçu au plus tard trois jours francs avant
# la réunion (art. 9 bis du décret) : le jour de réception et celui de
# l'assemblée ne comptent pas.
JOURS_FRANCS_VPC = 3

MAJORITES = [
    ("art24", "Article 24"),
    ("art25", "Article 25 (passerelle 25-1)"),
    ("art26", "Article 26"),
    ("unanimite", "Unanimité"),
    ("information", "Information – sans vote"),
    ("rubrique", "Titre de rubrique"),
]

LIBELLES_MAJORITE = {
    "art24": "Article 24 – majorité des voix exprimées des copropriétaires présents, représentés "
             "ou ayant voté par correspondance",
    "art25": "Article 25 – majorité des voix de tous les copropriétaires ; à défaut, si le projet a "
             "recueilli au moins le tiers de ces voix, second vote immédiat à la majorité de "
             "l'article 24 (article 25-1)",
    "art26": "Article 26 – majorité des membres du syndicat représentant au moins les deux tiers des "
             "voix ; à défaut, si le projet a recueilli l'approbation de la moitié des membres "
             "représentant au moins le tiers des voix, second vote immédiat à la majorité de "
             "l'article 25",
    "unanimite": "Unanimité des voix de tous les copropriétaires",
    "information": "Point d'information – sans vote",
    "rubrique": "",
}
ABREGES_MAJORITE = {
    "art24": "Article 24", "art25": "Articles 25 et 25-1", "art26": "Article 26",
    "unanimite": "Unanimité", "information": "Sans vote", "rubrique": "",
}


class AssembleeGenerale(models.Model):
    _name = "coproerp.ag"
    _description = "Assemblée générale des copropriétaires"
    _inherit = ["mail.thread"]
    _order = "date_ag desc, id desc"

    name = fields.Char(string="Libellé", compute="_compute_name", store=True)
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="restrict",
        tracking=True,
    )
    type_ag = fields.Selection(
        [("ordinaire", "Assemblée générale ordinaire"), ("extraordinaire", "Assemblée générale extraordinaire")],
        string="Type", required=True, default="ordinaire", tracking=True,
    )
    date_ag = fields.Date(string="Date de l'assemblée", required=True, tracking=True)
    urgence = fields.Boolean(
        string="Convocation en délai d'urgence",
        help="En cas d'urgence, le délai de 21 jours ne s'impose pas (art. 9 du décret du 17 mars 1967). "
             "L'urgence doit être réelle et justifiée : à défaut, l'assemblée encourt l'annulation.",
        tracking=True,
    )
    heure = fields.Float(string="Heure", default=18.0, help="Heure de début (ex. 17:30).")
    lieu_nom = fields.Char(string="Lieu", help="Ex. : Cabinet du syndic, salle de l'immeuble…")
    lieu_adresse = fields.Text(string="Adresse du lieu")
    visioconference = fields.Boolean(
        string="Participation à distance possible",
        help="Participation par visioconférence ou autre moyen de communication électronique "
             "(art. 17-1 A de la loi du 10 juillet 1965, art. 13-1 du décret).",
    )
    modalites_visio = fields.Text(string="Modalités de participation à distance")
    date_convocation = fields.Date(string="Date de la convocation", default=fields.Date.context_today)
    date_limite_presentation = fields.Date(
        string="Première présentation au plus tard le", compute="_compute_dates",
        help="Le délai de 21 jours court à compter du lendemain de la première présentation de la "
             "lettre recommandée (art. 9 et 64 du décret du 17 mars 1967).",
    )
    date_limite_vpc = fields.Date(
        string="Votes par correspondance reçus au plus tard le", compute="_compute_dates",
        help="Trois jours francs avant la réunion (art. 9 bis du décret).",
    )
    adresse_vpc = fields.Text(
        string="Adresse postale de retour des formulaires",
        help="Par défaut, l'adresse du syndic.",
    )
    email_vpc = fields.Char(
        string="Adresse électronique de retour des formulaires",
        help="Un formulaire adressé par voie électronique à cette adresse est présumé reçu le jour de son envoi.",
    )
    consultation_pieces = fields.Text(
        string="Consultation des pièces justificatives",
        help="Modalités de consultation des pièces justificatives des charges entre la convocation et "
             "l'assemblée (art. 18-1 de la loi, art. 9-1 du décret) : au moins un jour ouvré, lieu et horaires.",
    )
    cle_voix_id = fields.Many2one(
        "coproerp.repartition", string="Clé des voix",
        domain="[('copropriete_id', '=', copropriete_id)]",
        help="Chaque copropriétaire dispose d'un nombre de voix correspondant à sa quote-part dans les "
             "parties communes (art. 22) : en principe la clé des charges communes générales.",
    )
    total_voix = fields.Integer(string="Total des voix du syndicat", related="cle_voix_id.total_tantiemes")
    cloture_id = fields.Many2one(
        "coproerp.cloture", string="Comptes à approuver",
        domain="[('copropriete_id', '=', copropriete_id)]",
        help="Exercice clos dont les comptes et annexes sont soumis à l'assemblée.",
    )
    documents_joints = fields.Text(
        string="Documents joints à la convocation",
        help="Un document par ligne (art. 11 du décret) : comptes et annexes, budget, contrat de syndic, devis…",
    )
    resolution_ids = fields.One2many("coproerp.ag.resolution", "ag_id", string="Ordre du jour", copy=True)
    convocation_ids = fields.One2many("coproerp.ag.convocation", "ag_id", string="Convocations")
    nombre_convocations = fields.Integer(compute="_compute_nombre_convocations")
    etat = fields.Selection(
        [("preparation", "En préparation"), ("convoquee", "Convoquée"), ("tenue", "Tenue"),
         ("annulee", "Annulée")],
        string="État", default="preparation", required=True, tracking=True, copy=False,
    )
    note = fields.Text(string="Observations")

    @api.depends("type_ag", "date_ag", "copropriete_id")
    def _compute_name(self):
        for ag in self:
            sigle = "AGO" if ag.type_ag == "ordinaire" else "AGE"
            ag.name = "%s du %s – %s" % (
                sigle, ag.date_ag.strftime("%d/%m/%Y") if ag.date_ag else "…", ag.copropriete_id.name or "")

    @api.depends("date_ag")
    def _compute_dates(self):
        for ag in self:
            if ag.date_ag:
                ag.date_limite_presentation = ag.date_ag - timedelta(days=DELAI_CONVOCATION + 1)
                ag.date_limite_vpc = ag.date_ag - timedelta(days=JOURS_FRANCS_VPC + 1)
            else:
                ag.date_limite_presentation = ag.date_limite_vpc = False

    def _compute_nombre_convocations(self):
        for ag in self:
            ag.nombre_convocations = len(ag.convocation_ids)

    @api.onchange("copropriete_id")
    def _onchange_copropriete_id(self):
        valeurs = self._valeurs_par_defaut(self.copropriete_id)
        for champ, valeur in valeurs.items():
            if not self[champ]:
                self[champ] = valeur

    @api.model
    def _valeurs_par_defaut(self, copro):
        if not copro:
            return {}
        cle = self.env["coproerp.repartition"].search([
            ("copropriete_id", "=", copro.id), ("type_repartition", "=", "charges_generales"),
        ], order="id", limit=1)
        cloture = self.env["coproerp.cloture"].search([("copropriete_id", "=", copro.id)], limit=1)
        syndic = copro.sudo().syndic_id
        adresse = "\n".join(x for x in [
            syndic.name, syndic.street, syndic.street2,
            " ".join(y for y in [syndic.zip, syndic.city] if y)] if x) if syndic else False
        gestionnaire = copro.sudo().gestionnaire_id
        return {
            "cle_voix_id": cle,
            "cloture_id": cloture,
            "adresse_vpc": adresse,
            "email_vpc": gestionnaire.email or (syndic.email if syndic else False),
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            copro = self.env["coproerp.copropriete"].browse(vals.get("copropriete_id"))
            for champ, valeur in self._valeurs_par_defaut(copro).items():
                if champ not in vals:
                    vals[champ] = valeur.id if isinstance(valeur, models.BaseModel) else valeur
        return super().create(vals_list)

    @api.constrains("cle_voix_id", "copropriete_id")
    def _check_cle(self):
        for ag in self:
            if ag.cle_voix_id and ag.cle_voix_id.copropriete_id != ag.copropriete_id:
                raise ValidationError("La clé des voix doit appartenir à la copropriété.")

    # ------------------------------------------------------------------
    def heure_texte(self):
        self.ensure_one()
        heures = int(self.heure or 0)
        minutes = int(round(((self.heure or 0) - heures) * 60))
        return "%dh%02d" % (heures, minutes)

    def resolutions_votees(self):
        """Résolutions soumises au vote, dans l'ordre (hors rubriques et informations)."""
        return self.resolution_ids.filtered(lambda r: r.majorite not in ("information", "rubrique"))

    def lignes_vote(self):
        """Lignes du formulaire de vote par correspondance : chaque résolution soumise
        au vote et, pour les articles 25 et 26, la ligne du second vote éventuel."""
        self.ensure_one()
        lignes = []
        for resolution in self.resolution_ids:
            if resolution.majorite == "rubrique":
                lignes.append({"rubrique": True, "titre": resolution.titre})
                continue
            lignes.append({
                "rubrique": False, "numero": resolution.numero, "titre": resolution.titre,
                "majorite": ABREGES_MAJORITE[resolution.majorite],
                "vote": resolution.majorite != "information",
            })
            if resolution.majorite in ("art25", "art26"):
                lignes.append({
                    "rubrique": False, "numero": "%s bis" % resolution.numero,
                    "titre": "%s – en cas de second vote" % resolution.titre,
                    "majorite": "Article 24 (art. 25-1)" if resolution.majorite == "art25"
                    else "Article 25 (art. 26, dernier alinéa)",
                    "vote": True,
                })
        return lignes

    def documents_liste(self):
        self.ensure_one()
        return [l.strip(" -•\t") for l in (self.documents_joints or "").splitlines() if l.strip(" -•\t")]

    def action_renumeroter(self):
        """Numérote les résolutions soumises au vote ou à information (1, 2, 3…)."""
        for ag in self:
            numero = 0
            for resolution in ag.resolution_ids.sorted("sequence"):
                if resolution.majorite == "rubrique":
                    resolution.numero = False
                    continue
                numero += 1
                resolution.numero = str(numero)
        return True

    # ------------------------------------------------------------------
    # Convocations
    # ------------------------------------------------------------------
    def _destinataires(self):
        """{partner: [(lot, voix)]} pour tous les lots de la copropriété.

        Le destinataire d'un lot est celui des appels de fonds (mandataire commun en
        cas d'indivision ou de démembrement, art. 23 de la loi)."""
        self.ensure_one()
        if not self.cle_voix_id:
            raise UserError("Indiquez la clé des voix (en principe les charges communes générales).")
        parts = {l.lot_id: l.tantiemes for l in self.cle_voix_id.line_ids if l.lot_id}
        lots = self.env["coproerp.lot"].search([("copropriete_id", "=", self.copropriete_id.id)], order="numero")
        destinataires = {}
        erreurs = []
        for lot in lots:
            if lot.propriete_syndicat:
                continue
            partner, erreur = lot._destinataire_appels(self.date_ag)
            if erreur:
                erreurs.append(erreur)
                continue
            if partner:
                destinataires.setdefault(partner, []).append((lot, parts.get(lot, 0)))
        if erreurs:
            raise UserError("Impossible de préparer les convocations :\n- " + "\n- ".join(erreurs))
        return destinataires

    def action_preparer_convocations(self):
        Mode = self.env["coproerp.notification.mode"]
        for ag in self:
            if ag.etat != "preparation":
                raise UserError("Les convocations ne peuvent être préparées que pour une assemblée en préparation.")
            if not ag.resolutions_votees() and not ag.resolution_ids:
                raise UserError("L'ordre du jour est vide.")
            ag.convocation_ids.filtered(lambda c: c.etat == "a_envoyer").unlink()
            deja = ag.convocation_ids.personne_id
            commandes = []
            for partner, lots in sorted(ag._destinataires().items(), key=lambda x: x[0].name or ""):
                if partner in deja:
                    continue
                mode, adresse = Mode.mode_au(partner, ag.date_convocation or fields.Date.context_today(ag))
                commandes.append(Command.create({
                    "personne_id": partner.id,
                    "lot_ids": [Command.set([lot.id for lot, _v in lots])],
                    "voix": sum(v for _l, v in lots),
                    "mode_envoi": "lre" if mode == "electronique" else "lrar",
                    "adresse_email": adresse or False,
                }))
            ag.write({"convocation_ids": commandes})
        return True

    def action_marquer_convoquee(self):
        for ag in self:
            if not ag.convocation_ids:
                raise UserError("Préparez d'abord les convocations.")
            ag.etat = "convoquee"
        return True

    def action_remettre_en_preparation(self):
        self.filtered(lambda a: a.etat == "convoquee").write({"etat": "preparation"})
        return True

    def action_annuler(self):
        self.write({"etat": "annulee"})
        return True

    def action_voir_convocations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Convocations",
            "res_model": "coproerp.ag.convocation",
            "view_mode": "list,form",
            "domain": [("ag_id", "=", self.id)],
            "context": {"default_ag_id": self.id},
        }

    def action_imprimer_projet(self):
        return self.env.ref("coproerp_ag.action_report_projet_resolutions").report_action(self)

    def action_imprimer_dossiers(self):
        self.ensure_one()
        if not self.convocation_ids:
            raise UserError("Préparez d'abord les convocations.")
        return self.env.ref("coproerp_ag.action_report_dossier_convocation").report_action(self.convocation_ids)


class Resolution(models.Model):
    _name = "coproerp.ag.resolution"
    _description = "Point de l'ordre du jour"
    _order = "ag_id, sequence, id"

    ag_id = fields.Many2one("coproerp.ag", string="Assemblée", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    numero = fields.Char(string="N°")
    titre = fields.Char(string="Intitulé", required=True)
    majorite = fields.Selection(MAJORITES, string="Majorité", required=True, default="art24")
    texte = fields.Text(string="Projet de résolution")
    documents = fields.Char(string="Documents joints", help="Pièces jointes à la convocation pour ce point.")
    demande_par_id = fields.Many2one(
        "res.partner", string="Inscrite à la demande de",
        help="Question inscrite à la demande d'un copropriétaire ou du conseil syndical (art. 10 du décret).",
    )

    def libelle_majorite(self):
        self.ensure_one()
        return LIBELLES_MAJORITE[self.majorite]

    def abrege_majorite(self):
        self.ensure_one()
        return ABREGES_MAJORITE[self.majorite]


class Convocation(models.Model):
    _name = "coproerp.ag.convocation"
    _description = "Convocation à l'assemblée générale"
    _order = "ag_id, personne_id"

    ag_id = fields.Many2one("coproerp.ag", string="Assemblée", required=True, ondelete="cascade", index=True)
    copropriete_id = fields.Many2one(related="ag_id.copropriete_id", store=True)
    personne_id = fields.Many2one("res.partner", string="Copropriétaire", required=True)
    lot_ids = fields.Many2many(
        "coproerp.lot", "coproerp_ag_convocation_lot_rel", "convocation_id", "lot_id", string="Lots")
    voix = fields.Integer(string="Voix")
    mode_envoi = fields.Selection(
        [("lre", "Lettre recommandée électronique"), ("lrar", "Lettre recommandée avec AR"),
         ("remise", "Remise contre émargement")],
        string="Notification", required=True, default="lrar",
    )
    adresse_email = fields.Char(string="Adresse électronique")
    numero_envoi = fields.Char(string="N° de recommandé / preuve de dépôt")
    date_envoi = fields.Date(string="Envoyée le")
    date_presentation = fields.Date(
        string="Première présentation / remise le",
        help="Date de première présentation de la lettre recommandée, de réception de la lettre "
             "recommandée électronique ou de remise contre émargement.",
    )
    delai_respecte = fields.Boolean(string="Délai de 21 jours respecté", compute="_compute_delai", store=True)
    etat = fields.Selection(
        [("a_envoyer", "À envoyer"), ("envoyee", "Envoyée")],
        string="État", default="a_envoyer", required=True,
    )

    @api.depends("date_presentation", "ag_id.date_ag", "ag_id.urgence")
    def _compute_delai(self):
        for convocation in self:
            date_ag = convocation.ag_id.date_ag
            convocation.delai_respecte = convocation.ag_id.urgence or bool(
                convocation.date_presentation and date_ag
                and (date_ag - convocation.date_presentation).days >= DELAI_CONVOCATION + 1)

    def action_marquer_envoyee(self):
        for convocation in self:
            convocation.write({
                "etat": "envoyee",
                "date_envoi": convocation.date_envoi or fields.Date.context_today(convocation),
            })
        return True

    def mode_libelle(self):
        self.ensure_one()
        return dict(self._fields["mode_envoi"].selection)[self.mode_envoi]

    def lots_texte(self):
        self.ensure_one()
        return ", ".join("lot %s%s" % (l.numero, (" (%s)" % l.designation) if l.designation else "")
                         for l in self.lot_ids)


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]


def date_longue(d, jour=True):
    if not d:
        return ""
    texte = "%s %s %s" % ("1er" if d.day == 1 else d.day, MOIS[d.month - 1], d.year)
    return ("%s %s" % (JOURS[d.weekday()], texte)) if jour else texte


class AssembleeGeneraleDates(models.Model):
    _inherit = "coproerp.ag"

    def adresse_vpc_ligne(self):
        self.ensure_one()
        return ", ".join(l.strip() for l in (self.adresse_vpc or "").splitlines() if l.strip())

    def date_longue(self, champ="date_ag", jour=True):
        self.ensure_one()
        return date_longue(self[champ], jour)
