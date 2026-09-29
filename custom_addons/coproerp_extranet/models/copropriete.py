from odoo import fields, models


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    # ---------------------------------------------------------------
    # Liens utilisés par l'extranet et ses règles d'accès
    # ---------------------------------------------------------------
    droit_ids = fields.One2many(
        "coproerp.droit",
        "copropriete_id",
        string="Droits sur les lots",
    )

    mandat_cs_ids = fields.One2many(
        "coproerp.cs.mandat",
        "copropriete_id",
        string="Conseil syndical",
    )

    extranet_document_ids = fields.One2many(
        "coproerp.extranet.document",
        "copropriete_id",
        string="Documents extranet",
    )

    actualite_ids = fields.One2many(
        "coproerp.actualite",
        "copropriete_id",
        string="Actualités",
    )

    # ---------------------------------------------------------------
    # Votre équipe
    # ---------------------------------------------------------------
    gestionnaire_id = fields.Many2one(
        "res.users",
        string="Gestionnaire",
        domain="[('share', '=', False)]",
    )

    comptable_id = fields.Many2one(
        "res.users",
        string="Comptable",
        domain="[('share', '=', False)]",
    )

    assistant_id = fields.Many2one(
        "res.users",
        string="Assistant(e)",
        domain="[('share', '=', False)]",
    )

    # ---------------------------------------------------------------
    # Modes de règlement (compte bancaire séparé du syndicat)
    # ---------------------------------------------------------------
    banque_titulaire = fields.Char(
        string="Titulaire du compte",
        help="En principe : « Syndicat des copropriétaires du ... ».",
    )
    banque_nom = fields.Char(string="Banque")
    banque_iban = fields.Char(string="IBAN du compte séparé")
    banque_bic = fields.Char(string="BIC")

    extranet_actif = fields.Boolean(
        string="Extranet ouvert",
        default=True,
        help="Décocher pour masquer temporairement cette copropriété de l'extranet.",
    )

    extranet_message = fields.Html(
        string="Message d'accueil extranet",
        sanitize=True,
    )

    extranet_email_contact = fields.Char(
        string="E-mail de contact extranet",
    )

    cs_membre_count = fields.Integer(
        string="Membres du conseil syndical",
        compute="_compute_cs_membre_count",
    )

    def _compute_cs_membre_count(self):
        for copro in self:
            copro.cs_membre_count = len(
                copro.mandat_cs_ids.filtered("en_cours")
            )

    extranet_depenses_visibilite = fields.Selection(
        [
            ("conseil_syndical", "Conseil syndical uniquement"),
            ("tous", "Tous les copropriétaires"),
        ],
        string="Relevé des dépenses visible par",
        default="conseil_syndical",
        required=True,
    )

    # ---------------------------------------------------------------
    # Situation comptable affichée sur l'extranet
    #
    # Ces méthodes sont appelées avec les droits de l'utilisateur connecté :
    # les règles d'accès limitent ce qu'elles renvoient (ses propres appels,
    # ou ceux de tout l'immeuble pour un conseiller syndical en mandat).
    #
    # Point d'extension : le futur module des règlements (ou la comptabilité
    # Odoo) complétera _extranet_mouvements() avec les écritures au crédit,
    # et _extranet_depenses() avec le relevé général des dépenses.
    # ---------------------------------------------------------------
    def _extranet_mouvements(self, partner_ids=None):
        """Mouvements du compte des copropriétaires de cette copropriété.

        Retourne une liste de dicts :
        {date, libelle, debit, credit, personne_id, appel_id}
        """
        self.ensure_one()
        domain = [("copropriete_id", "=", self.id)]
        if partner_ids is not None:
            domain.append(("personne_id", "in", list(partner_ids)))
        appels = self.env["coproerp.appel.charge"].search(domain)
        types = dict(
            appels._fields["type_appel"]._description_selection(self.env)
        )
        mouvements = []
        for appel in appels:
            libelle = "Appel de fonds %s - %s" % (
                appel.reference or "",
                types.get(appel.type_appel, ""),
            )
            if appel.date_debut_periode and appel.date_fin_periode:
                libelle += " du %s au %s" % (
                    appel.date_debut_periode.strftime("%d/%m/%Y"),
                    appel.date_fin_periode.strftime("%d/%m/%Y"),
                )
            mouvements.append(
                {
                    # Date d'exigibilité, comme sur le relevé de compte des avis
                    "date": appel.date_echeance or appel.date_appel,
                    "libelle": libelle,
                    "debit": appel.total_appel,
                    "credit": 0.0,
                    "personne_id": appel.personne_id.id,
                    "appel_id": appel.id,
                }
            )
        return mouvements

    def _extranet_ecritures(self, partner_ids):
        """Écritures d'un copropriétaire, triées, avec solde progressif
        (solde positif = somme due par le copropriétaire)."""
        mouvements = sorted(
            self._extranet_mouvements(partner_ids),
            key=lambda m: (m["date"] or fields.Date.today(), m.get("appel_id") or 0),
        )
        solde = 0.0
        for mouvement in mouvements:
            solde += (mouvement["debit"] or 0.0) - (mouvement["credit"] or 0.0)
            mouvement["solde"] = round(solde, 2)
        return mouvements

    def _extranet_soldes_coproprietaires(self):
        """Solde par copropriétaire (réservé au conseil syndical)."""
        self.ensure_one()
        lignes = {}
        droits = self.sudo().droit_ids.filtered("acces_extranet")
        for droit in droits.sorted("lot_numero"):
            ligne = lignes.setdefault(
                droit.personne_id.id,
                {
                    "id": droit.personne_id.id,
                    "numero": droit.personne_id.ref or "",
                    "nom": droit.personne_id.name or "",
                    "lots": [],
                    "solde": 0.0,
                },
            )
            ligne["lots"].append(droit.lot_numero or "")
        for mouvement in self._extranet_mouvements():
            ligne = lignes.get(mouvement["personne_id"])
            if ligne is None:
                personne = self.env["res.partner"].sudo().browse(mouvement["personne_id"])
                ligne = lignes.setdefault(
                    personne.id,
                    {
                        "id": personne.id,
                        "numero": personne.ref or "",
                        "nom": personne.name or "",
                        "lots": [],
                        "solde": 0.0,
                    },
                )
            ligne["solde"] += (mouvement["debit"] or 0.0) - (mouvement["credit"] or 0.0)
        resultat = sorted(lignes.values(), key=lambda l: l["nom"].lower())
        for ligne in resultat:
            ligne["lots"] = ", ".join(sorted(set(ligne["lots"])))
            ligne["solde"] = round(ligne["solde"], 2)
        return resultat

    def _extranet_depenses(self):
        """Relevé général des dépenses : liste de dicts
        {compte, libelle_compte, date, libelle, debit, credit}.

        Vide tant que la comptabilité des dépenses n'est pas en place.
        """
        self.ensure_one()
        return []
