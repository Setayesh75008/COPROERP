import base64
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

TYPES_CONTRAT = [
    ("assurance", "Assurance de l'immeuble (multirisque)"),
    ("dommages_ouvrage", "Assurance dommages-ouvrage"),
    ("entretien", "Contrat d'entretien ou de maintenance"),
    ("autre", "Autre contrat"),
]
NATURES_TRAVAUX = [
    ("ravalement", "Ravalement"),
    ("toiture", "Toiture, couverture"),
    ("ascenseur", "Ascenseur (remplacement, mise aux normes)"),
    ("chauffage", "Chaudière, chauffage collectif"),
    ("canalisations", "Canalisations, colonnes"),
    ("etancheite", "Étanchéité, terrasses"),
    ("electricite", "Électricité des parties communes"),
    ("securite", "Sécurité incendie"),
    ("energetique", "Rénovation énergétique, isolation"),
    ("autre", "Autres travaux importants"),
]
TYPES_DIAGNOSTIC = [
    ("amiante", "Dossier technique amiante (DTA)"),
    ("plomb", "Constat de risque d'exposition au plomb (parties communes)"),
    ("dpe", "Diagnostic de performance énergétique collectif"),
    ("dtg", "Diagnostic technique global (DTG)"),
    ("audit", "Audit énergétique"),
    ("ppt", "Projet de plan pluriannuel de travaux"),
    ("termites", "État relatif aux termites ou mérules"),
    ("ascenseur", "Contrôle technique quinquennal de l'ascenseur"),
    ("gaz", "Diagnostic des installations de gaz / électricité"),
    ("autre", "Autre diagnostic ou étude technique"),
]


class Contrat(models.Model):
    """Contrats et assurances de l'immeuble (carnet d'entretien)."""

    _name = "coproerp.contrat"
    _description = "Contrat ou assurance de l'immeuble"
    _inherit = ["mail.thread"]
    _order = "type_contrat, date_echeance, id"

    name = fields.Char(string="Objet", required=True, tracking=True)
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="cascade")
    type_contrat = fields.Selection(TYPES_CONTRAT, string="Type", required=True, default="entretien", tracking=True)
    equipement = fields.Char(string="Équipement concerné", help="Ex. : ascenseur, chaudière, portes automatiques…")
    prestataire_id = fields.Many2one("res.partner", string="Prestataire / assureur", tracking=True)
    reference = fields.Char(string="N° de contrat ou de police")
    date_debut = fields.Date(string="Date d'effet")
    date_echeance = fields.Date(string="Échéance", tracking=True)
    tacite_reconduction = fields.Boolean(string="Tacite reconduction", default=True)
    preavis_mois = fields.Integer(string="Préavis de résiliation (mois)", default=3)
    date_limite_resiliation = fields.Date(
        string="Résiliation possible jusqu'au", compute="_compute_resiliation", store=True)
    montant_annuel = fields.Float(string="Montant annuel TTC", digits=(16, 2))
    travaux_id = fields.Many2one(
        "coproerp.travaux", string="Opération de travaux couverte",
        domain="[('copropriete_id', '=', copropriete_id)]",
        help="Pour une assurance dommages-ouvrage : l'opération de travaux garantie.")
    date_fin_garantie = fields.Date(
        string="Fin de la garantie", help="Dommages-ouvrage : en principe dix ans après la réception des travaux.")
    actif = fields.Boolean(string="En cours", default=True, tracking=True)
    document = fields.Binary(string="Contrat (PDF)", attachment=True)
    document_nom = fields.Char(string="Nom du fichier")
    note = fields.Text(string="Observations")
    alerte = fields.Boolean(string="À examiner", compute="_compute_alerte",
                            help="Échéance ou date limite de résiliation dans les 60 jours.")

    @api.depends("date_echeance", "preavis_mois")
    def _compute_resiliation(self):
        for contrat in self:
            contrat.date_limite_resiliation = (
                contrat.date_echeance - relativedelta(months=contrat.preavis_mois or 0)
                if contrat.date_echeance else False)

    def _compute_alerte(self):
        aujourdhui = fields.Date.context_today(self)
        horizon = aujourdhui + timedelta(days=60)
        for contrat in self:
            dates = [d for d in (contrat.date_limite_resiliation, contrat.date_echeance) if d]
            contrat.alerte = bool(contrat.actif and dates and min(dates) <= horizon)

    @api.constrains("date_debut", "date_echeance")
    def _check_dates(self):
        for contrat in self:
            if contrat.date_debut and contrat.date_echeance and contrat.date_echeance < contrat.date_debut:
                raise ValidationError("L'échéance ne peut pas précéder la date d'effet.")

    def garantie_en_cours(self, date=None):
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        return self.actif and (not self.date_fin_garantie or self.date_fin_garantie >= date)


class CarnetTravaux(models.Model):
    """Travaux importants réalisés sur l'immeuble."""

    _name = "coproerp.carnet.travaux"
    _description = "Travaux importants réalisés (carnet d'entretien)"
    _order = "annee desc, id desc"

    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="cascade")
    annee = fields.Integer(string="Année de réalisation", required=True)
    nature = fields.Selection(NATURES_TRAVAUX, string="Nature", required=True, default="autre")
    name = fields.Char(string="Description", required=True)
    entreprise_id = fields.Many2one("res.partner", string="Entreprise")
    montant = fields.Float(string="Montant TTC", digits=(16, 2))
    date_reception = fields.Date(string="Date de réception des travaux")
    travaux_id = fields.Many2one(
        "coproerp.travaux", string="Opération de travaux", domain="[('copropriete_id', '=', copropriete_id)]")
    assurance_do_id = fields.Many2one(
        "coproerp.contrat", string="Assurance dommages-ouvrage",
        domain="[('copropriete_id', '=', copropriete_id), ('type_contrat', '=', 'dommages_ouvrage')]")

    @api.constrains("annee")
    def _check_annee(self):
        for ligne in self:
            if ligne.annee < 1800 or ligne.annee > fields.Date.context_today(ligne).year:
                raise ValidationError("L'année de réalisation des travaux est invalide.")


class Diagnostic(models.Model):
    """Diagnostics et études techniques de l'immeuble."""

    _name = "coproerp.diagnostic"
    _description = "Diagnostic technique de l'immeuble"
    _order = "type_diagnostic, date_realisation desc, id desc"

    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="cascade")
    type_diagnostic = fields.Selection(TYPES_DIAGNOSTIC, string="Diagnostic", required=True)
    name = fields.Char(string="Intitulé", compute="_compute_name", store=True, readonly=False)
    date_realisation = fields.Date(string="Réalisé le", required=True)
    prestataire_id = fields.Many2one("res.partner", string="Diagnostiqueur / bureau d'études")
    conclusion = fields.Text(string="Conclusions")
    date_validite = fields.Date(string="Valable jusqu'au / à renouveler le")
    document = fields.Binary(string="Rapport (PDF)", attachment=True)
    document_nom = fields.Char(string="Nom du fichier")
    a_renouveler = fields.Boolean(string="À renouveler", compute="_compute_a_renouveler")

    @api.depends("type_diagnostic")
    def _compute_name(self):
        libelles = dict(TYPES_DIAGNOSTIC)
        for diagnostic in self:
            if not diagnostic.name:
                diagnostic.name = libelles.get(diagnostic.type_diagnostic, "")

    def _compute_a_renouveler(self):
        horizon = fields.Date.context_today(self) + timedelta(days=90)
        for diagnostic in self:
            diagnostic.a_renouveler = bool(diagnostic.date_validite and diagnostic.date_validite <= horizon)


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    contrat_ids = fields.One2many("coproerp.contrat", "copropriete_id", string="Contrats et assurances")
    carnet_travaux_ids = fields.One2many("coproerp.carnet.travaux", "copropriete_id", string="Travaux réalisés")
    diagnostic_ids = fields.One2many("coproerp.diagnostic", "copropriete_id", string="Diagnostics techniques")
    carnet_document_id = fields.Many2one(
        "coproerp.extranet.document", string="Carnet publié sur l'extranet", readonly=True, copy=False)
    carnet_etudes = fields.Text(
        string="Études techniques et informations complémentaires",
        help="Informations facultatives que l'assemblée a décidé de faire figurer au carnet (art. 4 du décret).")

    def action_reprendre_travaux_termines(self):
        """Ajoute au carnet les opérations de travaux terminées ou clôturées qui n'y figurent pas."""
        for copro in self:
            deja = copro.carnet_travaux_ids.travaux_id
            operations = self.env["coproerp.travaux"].search([
                ("copropriete_id", "=", copro.id), ("etat", "in", ("termine", "cloture")),
                ("id", "not in", deja.ids)])
            commandes = []
            for operation in operations:
                date = operation.date_fin_prevue or operation.date_vote
                depenses = self.env["coproerp.depense"].search([
                    ("travaux_id", "=", operation.id), ("etat", "=", "validee")])
                entreprise = depenses[:1].fournisseur_id
                commandes.append(Command.create({
                    "annee": date.year if date else fields.Date.context_today(copro).year,
                    "name": operation.name,
                    "travaux_id": operation.id,
                    "entreprise_id": entreprise.id or False,
                    "montant": sum(depenses.mapped("montant_total")),
                }))
            copro.write({"carnet_travaux_ids": commandes})
        return True

    def action_imprimer_carnet(self):
        return self.env.ref("coproerp_carnet_entretien.action_report_carnet").report_action(self)

    def action_publier_carnet(self):
        rapport = self.env.ref("coproerp_carnet_entretien.action_report_carnet")
        categorie = self.env.ref("coproerp_extranet.categorie_carnet_entretien")
        for copro in self:
            pdf, _type = self.env["ir.actions.report"]._render_qweb_pdf(rapport.report_name, copro.ids)
            aujourdhui = fields.Date.context_today(copro)
            document = self.env["coproerp.extranet.document"].create({
                "name": "Carnet d'entretien de l'immeuble (mis à jour le %s)" % aujourdhui.strftime("%d/%m/%Y"),
                "copropriete_id": copro.id,
                "categorie_id": categorie.id,
                "visibilite": "tous",
                "fichier": base64.b64encode(pdf),
                "nom_fichier": "Carnet d'entretien %s.pdf" % aujourdhui.strftime("%Y-%m-%d"),
                "date_document": aujourdhui,
            })
            document.action_publier()
            copro.carnet_document_id = document
        return True

    # -- données du carnet -------------------------------------------------
    def carnet_donnees(self):
        self.ensure_one()
        aujourdhui = fields.Date.context_today(self)
        contrats = self.contrat_ids
        travaux_votes = self.env["coproerp.travaux"].search([
            ("copropriete_id", "=", self.id), ("etat", "in", ("vote", "financement", "en_cours"))],
            order="date_vote")
        echeances = self.env["coproerp.travaux.echeance"].search([
            ("travaux_id", "in", travaux_votes.ids)], order="date_echeance")
        return {
            "assurances": contrats.filtered(lambda c: c.type_contrat == "assurance" and c.actif),
            "dommages_ouvrage": contrats.filtered(
                lambda c: c.type_contrat == "dommages_ouvrage" and c.garantie_en_cours(aujourdhui)),
            "entretien": contrats.filtered(lambda c: c.type_contrat in ("entretien", "autre") and c.actif),
            "travaux": self.carnet_travaux_ids.sorted(lambda t: (-t.annee, t.id)),
            "travaux_votes": travaux_votes,
            "echeances": echeances,
            "diagnostics": self.diagnostic_ids.sorted(lambda d: (d.type_diagnostic, d.date_realisation)),
            "date": aujourdhui,
        }

    def libelle_selection(self, record, champ):
        valeur = record[champ]
        return dict(record._fields[champ].selection).get(valeur, "") if valeur else ""

    def date_fr(self, valeur):
        return valeur.strftime("%d/%m/%Y") if valeur else "–"

    def fmt_euros(self, valeur):
        return "{:,.2f}".format(valeur or 0.0).replace(",", " ").replace(".", ",") + " €"
