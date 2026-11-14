import calendar
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Règles propres à chaque type de bail.
#   duree : durée par défaut en mois ; dg : plafond du dépôt de garantie en mois de loyer hors charges
#   (None = libre) ; preavis : préavis du locataire en mois ; indice : indice de révision par défaut.
TYPES_BAIL = {
    "habitation_vide": {
        "label": "Habitation non meublée (loi du 6 juillet 1989)", "duree": 36, "dg": 1, "preavis": 3,
        "indice": "irl", "tva": False},
    "habitation_meublee": {
        "label": "Habitation meublée (titre I bis de la loi de 1989)", "duree": 12, "dg": 2, "preavis": 1,
        "indice": "irl", "tva": False},
    "etudiant": {
        "label": "Meublé étudiant (9 mois, non reconductible)", "duree": 9, "dg": 2, "preavis": 1,
        "indice": "irl", "tva": False},
    "mobilite": {
        "label": "Bail mobilité (1 à 10 mois, sans dépôt de garantie)", "duree": 10, "dg": 0, "preavis": 1,
        "indice": "aucun", "tva": False},
    "commercial": {
        "label": "Bail commercial (9 ans, articles L. 145-1 et s. du code de commerce)", "duree": 108, "dg": None,
        "preavis": 6, "indice": "ilc", "tva": True},
    "professionnel": {
        "label": "Bail professionnel (6 ans minimum, art. 57 A de la loi du 23 décembre 1986)", "duree": 72,
        "dg": None, "preavis": 6, "indice": "ilat", "tva": True},
    "stationnement": {
        "label": "Parking, garage ou box loué seul (code civil)", "duree": 12, "dg": None, "preavis": 1,
        "indice": "irl", "tva": False},
    "saisonnier": {
        "label": "Location saisonnière (90 jours au plus)", "duree": 1, "dg": None, "preavis": 0,
        "indice": "aucun", "tva": False},
    "code_civil": {
        "label": "Bail de droit commun (code civil : résidence secondaire, personne morale…)", "duree": 12,
        "dg": None, "preavis": 1, "indice": "irl", "tva": False},
}
INDICES = [("irl", "IRL (indice de référence des loyers)"), ("ilc", "ILC (loyers commerciaux)"),
           ("ilat", "ILAT (loyers des activités tertiaires)"), ("icc", "ICC (coût de la construction)"),
           ("aucun", "Pas de révision")]
HABITATION = ("habitation_vide", "habitation_meublee", "etudiant", "mobilite")


def fin_de_mois(jour):
    return jour.replace(day=calendar.monthrange(jour.year, jour.month)[1])


class Bail(models.Model):
    _name = "coproerp.locatif.bail"
    _description = "Bail"
    _inherit = ["mail.thread"]
    _order = "date_debut desc, id desc"

    name = fields.Char(string="Référence", readonly=True, copy=False, default="/")
    type_bail = fields.Selection([(cle, regle["label"]) for cle, regle in TYPES_BAIL.items()],
                                 string="Type de bail", required=True, default="habitation_vide", tracking=True)
    bien_id = fields.Many2one("coproerp.locatif.bien", string="Bien loué", required=True, tracking=True)
    mandat_id = fields.Many2one("coproerp.locatif.mandat", string="Mandat", compute="_compute_mandat", store=True,
                                readonly=False)
    proprietaire_id = fields.Many2one(related="mandat_id.proprietaire_id", store=True, string="Propriétaire")
    locataire_id = fields.Many2one("res.partner", string="Locataire principal", required=True, tracking=True,
                                   help="Celui au nom duquel sont tenus le compte et les avis d'échéance.")
    locataire_ids = fields.Many2many("res.partner", "coproerp_locatif_bail_locataire_rel", "bail_id", "partner_id",
                                     string="Colocataires / cotitulaires")
    garant_ids = fields.Many2many("res.partner", "coproerp_locatif_bail_garant_rel", "bail_id", "partner_id",
                                  string="Garants (cautions)")
    date_signature = fields.Date(string="Signé le")
    date_debut = fields.Date(string="Prise d'effet", required=True, tracking=True)
    duree_mois = fields.Integer(string="Durée (mois)", compute="_compute_regles", store=True, readonly=False)
    date_fin = fields.Date(string="Fin de la période en cours", compute="_compute_date_fin", store=True,
                           readonly=False)
    date_sortie = fields.Date(string="Date de sortie du locataire", tracking=True,
                              help="Les avis d'échéance ne sont plus émis après cette date ; le dernier est proratisé.")
    preavis_mois = fields.Integer(string="Préavis du locataire (mois)", compute="_compute_regles", store=True,
                                  readonly=False)
    loyer_hc = fields.Float(string="Loyer mensuel hors charges", digits=(16, 2), required=True, tracking=True)
    charges = fields.Float(string="Charges mensuelles", digits=(16, 2), tracking=True)
    mode_charges = fields.Selection([("provision", "Provision régularisée chaque année"),
                                     ("forfait", "Forfait (non régularisé)")],
                                    string="Charges", default="provision", required=True,
                                    help="Le forfait n'est possible qu'en meublé, en colocation à bail unique "
                                         "et hors habitation.")
    tva = fields.Boolean(string="Loyer soumis à TVA", compute="_compute_regles", store=True, readonly=False)
    taux_tva = fields.Float(string="Taux de TVA (%)", default=20.0)
    depot_garantie = fields.Float(string="Dépôt de garantie", digits=(16, 2), tracking=True)
    depot_maximum = fields.Float(string="Plafond légal du dépôt", compute="_compute_depot_maximum")
    periodicite = fields.Selection([("mensuel", "Mensuelle"), ("trimestriel", "Trimestrielle")],
                                   string="Périodicité", default="mensuel", required=True)
    terme = fields.Selection([("echoir", "À échoir (payable d'avance)"), ("echu", "Échu (en fin de période)")],
                             string="Terme", default="echoir", required=True)
    jour_paiement = fields.Integer(string="Jour de paiement", default=1,
                                   help="Pour un terme à échoir : jour du mois où le loyer est exigible.")
    indice = fields.Selection(INDICES, string="Indice de révision", compute="_compute_regles", store=True,
                              readonly=False)
    trimestre_reference = fields.Char(string="Trimestre de référence de l'indice", help="Par exemple « T2 2026 ».")
    valeur_indice = fields.Float(string="Valeur de l'indice de référence", digits=(8, 2))
    quittancement_auto = fields.Boolean(string="Quittancement automatique", default=True)
    etat = fields.Selection([("brouillon", "En préparation"), ("en_cours", "En cours"), ("termine", "Terminé")],
                            string="État", default="brouillon", required=True, tracking=True)
    echeance_ids = fields.One2many("coproerp.locatif.echeance", "bail_id", string="Avis d'échéance")
    encaissement_ids = fields.One2many("coproerp.locatif.encaissement", "bail_id", string="Encaissements")
    relance_ids = fields.One2many("coproerp.locatif.relance", "bail_id", string="Relances")
    solde = fields.Float(string="Reste dû", compute="_compute_solde", digits=(16, 2),
                         help="Montant des avis d'échéance non encore payés, avances déduites.")
    plus_ancienne_impayee = fields.Date(string="Échéance impayée la plus ancienne", compute="_compute_solde")
    jours_retard = fields.Integer(string="Jours de retard", compute="_compute_solde")
    note = fields.Text(string="Clauses particulières")

    # ------------------------------------------------------------------
    @api.depends("bien_id")
    def _compute_mandat(self):
        for bail in self:
            if bail.etat == "brouillon" or not bail.mandat_id:
                bail.mandat_id = bail.bien_id.mandat_id

    @api.depends("type_bail", "bien_id.zone_tendue", "mandat_id.proprietaire_id.is_company")
    def _compute_regles(self):
        for bail in self:
            regle = TYPES_BAIL[bail.type_bail or "habitation_vide"]
            duree = regle["duree"]
            if bail.type_bail == "habitation_vide" and bail.mandat_id.proprietaire_id.is_company:
                duree = 72  # 6 ans quand le bailleur est une personne morale (art. 10 de la loi de 1989)
            preavis = regle["preavis"]
            if bail.type_bail == "habitation_vide" and bail.bien_id.zone_tendue:
                preavis = 1
            bail.duree_mois = duree
            bail.preavis_mois = preavis
            bail.indice = regle["indice"]
            bail.tva = regle["tva"]

    @api.depends("date_debut", "duree_mois", "type_bail")
    def _compute_date_fin(self):
        for bail in self:
            if bail.date_debut and bail.duree_mois and bail.type_bail != "saisonnier":
                bail.date_fin = bail.date_debut + relativedelta(months=bail.duree_mois, days=-1)
            else:
                bail.date_fin = bail.date_fin or False  # saisonnier : date saisie

    @api.depends("type_bail", "loyer_hc")
    def _compute_depot_maximum(self):
        for bail in self:
            plafond = TYPES_BAIL[bail.type_bail or "habitation_vide"]["dg"]
            bail.depot_maximum = -1.0 if plafond is None else round(plafond * bail.loyer_hc, 2)

    def _compute_solde(self):
        aujourdhui = fields.Date.context_today(self)
        for bail in self:
            lignes = bail._lignes_compte_locataire()
            bail.solde = round(sum(lignes.mapped("amount_residual")), 2)
            impayees = bail.echeance_ids.filtered(lambda e: e.etat in ("emise", "partielle")
                                                  and e.date_echeance <= aujourdhui)
            premiere = min(impayees.mapped("date_echeance")) if impayees else False
            bail.plus_ancienne_impayee = premiere
            bail.jours_retard = (aujourdhui - premiere).days if premiere else 0

    @api.constrains("type_bail", "depot_garantie", "loyer_hc", "duree_mois", "date_debut", "date_fin", "mode_charges",
                    "jour_paiement")
    def _check_regles(self):
        for bail in self:
            regle = TYPES_BAIL[bail.type_bail]
            if bail.loyer_hc < 0 or bail.charges < 0 or bail.depot_garantie < 0:
                raise ValidationError("Le loyer, les charges et le dépôt de garantie ne peuvent pas être négatifs.")
            if regle["dg"] is not None and bail.depot_garantie > round(regle["dg"] * bail.loyer_hc, 2) + 0.005:
                if regle["dg"] == 0:
                    raise ValidationError("Aucun dépôt de garantie ne peut être demandé pour un bail mobilité "
                                          "(art. 25-17 de la loi de 1989).")
                raise ValidationError(
                    "Le dépôt de garantie d'un bail « %s » ne peut pas dépasser %d mois de loyer hors charges, "
                    "soit %.2f €." % (regle["label"], regle["dg"], regle["dg"] * bail.loyer_hc))
            if bail.type_bail == "mobilite" and not 1 <= bail.duree_mois <= 10:
                raise ValidationError("Un bail mobilité dure de 1 à 10 mois (art. 25-14 de la loi de 1989).")
            if bail.type_bail == "habitation_vide" and bail.duree_mois < 36:
                raise ValidationError("Un bail d'habitation non meublée dure au moins 3 ans (6 ans si le bailleur "
                                      "est une personne morale).")
            if bail.type_bail == "habitation_meublee" and bail.duree_mois < 12:
                raise ValidationError("Un bail meublé dure au moins un an (9 mois pour un étudiant : choisissez "
                                      "« Meublé étudiant »).")
            if bail.type_bail == "commercial" and bail.duree_mois < 108:
                raise ValidationError("Un bail commercial dure au moins 9 ans (sauf bail dérogatoire, à saisir "
                                      "en bail de droit commun).")
            if bail.type_bail == "professionnel" and bail.duree_mois < 72:
                raise ValidationError("Un bail professionnel dure au moins 6 ans.")
            if bail.type_bail == "saisonnier":
                if not bail.date_fin:
                    raise ValidationError("Indiquez la date de fin de la location saisonnière.")
                if (bail.date_fin - bail.date_debut).days + 1 > 90:
                    raise ValidationError("Une location saisonnière ne peut pas dépasser 90 jours consécutifs.")
            if bail.mode_charges == "forfait" and bail.type_bail == "habitation_vide":
                raise ValidationError("Les charges d'un logement non meublé sont des provisions régularisées "
                                      "chaque année (art. 23 de la loi de 1989), pas un forfait.")
            if not 1 <= bail.jour_paiement <= 28:
                raise ValidationError("Le jour de paiement doit être compris entre 1 et 28.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.locatif.bail") or "/"
        baux = super().create(vals_list)
        for bail in baux:
            bail.locataire_id.role_locataire = True
            if bail.locataire_id not in bail.locataire_ids:
                bail.locataire_ids = [(4, bail.locataire_id.id)]
            bail.garant_ids.write({"role_garant": True})
        return baux

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def action_activer(self):
        """Bail signé : il entre en vigueur ; le dépôt de garantie est appelé."""
        self.env["coproerp.locatif.dossier"].actif()
        for bail in self.filtered(lambda b: b.etat == "brouillon"):
            if not bail.mandat_id or bail.mandat_id.etat != "actif":
                raise UserError("Le bien doit être confié par un mandat de gestion en cours.")
            autre = self.search([("bien_id", "=", bail.bien_id.id), ("etat", "=", "en_cours"), ("id", "!=", bail.id)])
            if autre and bail.type_bail != "stationnement":
                raise UserError("Le bien est déjà loué (bail %s)." % autre[0].name)
            bail.etat = "en_cours"
            if bail.depot_garantie:
                self.env["coproerp.locatif.echeance"].creer_depot_garantie(bail)
        return True

    def action_terminer(self):
        for bail in self.filtered(lambda b: b.etat == "en_cours"):
            if not bail.date_sortie:
                raise UserError("Indiquez la date de sortie du locataire.")
            bail.generer_echeances(bail.date_sortie)
            bail.etat = "termine"
        return True

    # ------------------------------------------------------------------
    # Quittancement
    # ------------------------------------------------------------------
    def _periodes(self, jusqu_au):
        """Périodes à quittancer : (début, fin) en mois civils (ou trimestres civils), du début du bail
        jusqu'à la période dont l'échéance tombe au plus tard « jusqu_au »."""
        self.ensure_one()
        pas = 3 if self.periodicite == "trimestriel" else 1
        fins = self.echeance_ids.filtered(
            lambda e: e.type_echeance == "loyer" and e.etat != "annulee").mapped("periode_fin")
        debut = max(fins) + timedelta(days=1) if fins else self.date_debut
        limites = [self.date_sortie]
        if self.type_bail in ("saisonnier", "mobilite", "etudiant"):
            limites.append(self.date_fin)  # baux non reconductibles
        limites = [d for d in limites if d]
        fin_bail = min(limites) if limites else None
        periodes = []
        while True:
            if fin_bail and debut > fin_bail:
                break
            mois_debut = debut.replace(day=1)
            if pas == 3:
                mois_debut = mois_debut.replace(month=((mois_debut.month - 1) // 3) * 3 + 1)
            fin = fin_de_mois(mois_debut + relativedelta(months=pas - 1))
            if fin_bail and fin > fin_bail:
                fin = fin_bail
            echeance = self._date_echeance(debut, fin)
            if echeance > jusqu_au:
                break
            periodes.append((debut, fin, echeance))
            debut = fin + timedelta(days=1)
        return periodes

    def _date_echeance(self, debut, fin):
        if self.terme == "echu":
            return fin
        jour = debut.replace(day=min(self.jour_paiement, calendar.monthrange(debut.year, debut.month)[1]))
        return max(jour, debut)

    def _prorata(self, debut, fin):
        """Fraction de la période facturée : jours occupés / jours de la période complète."""
        pas = 3 if self.periodicite == "trimestriel" else 1
        mois_debut = debut.replace(day=1)
        if pas == 3:
            mois_debut = mois_debut.replace(month=((mois_debut.month - 1) // 3) * 3 + 1)
        complete_debut = mois_debut
        complete_fin = fin_de_mois(mois_debut + relativedelta(months=pas - 1))
        jours_complets = (complete_fin - complete_debut).days + 1
        jours = (fin - debut).days + 1
        return 1.0 if jours >= jours_complets else jours / jours_complets

    def generer_echeances(self, jusqu_au=None):
        """Émet les avis d'échéance jusqu'à la date donnée (par défaut : aujourd'hui)."""
        jusqu_au = jusqu_au or fields.Date.context_today(self)
        Echeance = self.env["coproerp.locatif.echeance"]
        crees = Echeance
        for bail in self.filtered(lambda b: b.etat == "en_cours"):
            for debut, fin, echeance in bail._periodes(jusqu_au):
                crees |= Echeance.creer_loyer(bail, debut, fin, echeance)
        return crees

    def action_generer_echeances(self):
        crees = self.generer_echeances(fields.Date.context_today(self) + timedelta(
            days=self.env["coproerp.locatif.dossier"].actif().delai_emission))
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": "Quittancement", "type": "success" if crees else "info", "sticky": False,
                       "message": "%d avis d'échéance émis." % len(crees) if crees else "Aucun avis à émettre."},
        }

    @api.model
    def _cron_quittancement(self):
        dossier = self.env["coproerp.locatif.dossier"].sudo().search([("company_id", "!=", False)], limit=1)
        if not dossier:
            return
        limite = fields.Date.context_today(self) + timedelta(days=dossier.delai_emission)
        self.search([("etat", "=", "en_cours"), ("quittancement_auto", "=", True)]).generer_echeances(limite)

    # ------------------------------------------------------------------
    # Compte du locataire
    # ------------------------------------------------------------------
    def _lignes_compte_locataire(self):
        """Lignes ouvertes du compte locataire (411) propres à ce bail."""
        self.ensure_one()
        moves = self.echeance_ids.move_id | self.encaissement_ids.move_id
        if not moves:
            return self.env["account.move.line"]
        dossier = self.env["coproerp.locatif.dossier"].sudo().search([("company_id", "!=", False)], limit=1)
        if not dossier:
            return self.env["account.move.line"]
        compte = dossier.compte("locataires")
        return moves.sudo().line_ids.filtered(
            lambda l: l.account_id == compte and not l.reconciled and l.parent_state == "posted")

    def lettrer(self):
        """Impute les paiements et avances du bail sur les échéances, de la plus ancienne à la plus récente."""
        for bail in self:
            lignes = bail._lignes_compte_locataire()
            debits = lignes.filtered(lambda l: l.balance > 0).sorted(lambda l: (l.date, l.id))
            credits = lignes.filtered(lambda l: l.balance < 0).sorted(lambda l: (l.date, l.id))
            for credit in credits:
                for debit in debits:
                    if credit.reconciled:
                        break
                    if not debit.reconciled:
                        (debit | credit).reconcile()
            bail.echeance_ids._maj_paiement()
            bail.invalidate_recordset(["solde", "plus_ancienne_impayee", "jours_retard"])
        return True

    def action_preparer_relance(self):
        self.ensure_one()
        relance = self.env["coproerp.locatif.relance"].preparer(self)
        return {"type": "ir.actions.act_window", "res_model": "coproerp.locatif.relance", "res_id": relance.id,
                "view_mode": "form"}

    def libelle_type(self):
        self.ensure_one()
        return TYPES_BAIL[self.type_bail]["label"]

    def locataires(self):
        self.ensure_one()
        return self.locataire_id | self.locataire_ids

    @api.model
    def date_fr(self, valeur):
        return valeur.strftime("%d/%m/%Y") if valeur else ""

    @api.model
    def euros(self, montant):
        return ("{:,.2f} €".format(montant or 0.0)).replace(",", " ").replace(".", ",")
