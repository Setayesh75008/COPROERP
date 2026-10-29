from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

# Libellés des classes de charges du plan comptable des copropriétés
# (décret n° 2005-240 du 14 mars 2005).
CLASSES_CHARGES = {
    "60": "Achats de matières et fournitures",
    "61": "Services extérieurs",
    "62": "Frais d'administration et honoraires",
    "63": "Impôts - taxes et versements assimilés",
    "64": "Frais de personnel",
    "66": "Charges financières des emprunts, agios ou autres",
    "67": "Charges pour travaux et opérations exceptionnelles",
    "68": "Dotations aux dépréciations sur créances douteuses",
}
# Produits pour opérations courantes ; les autres comptes 7 (hors 705 et 781)
# relèvent des travaux et opérations exceptionnelles.
PRODUITS_COURANTS = ("701", "714", "716")
PRODUITS_EXCLUS = ("705", "781")  # 705 : fonds de travaux (mis en réserve au 105)


def _arrondi(valeur):
    return round(valeur or 0.0, 2)


class Cloture(models.Model):
    """Clôture d'un exercice et annexes comptables (décret n° 2005-240).

    Les annexes sont calculées à partir des écritures comptables du dossier
    du syndicat ; elles peuvent être imprimées à tout moment (« projet »)
    puis, une fois l'exercice clôturé, jointes à la convocation de
    l'assemblée appelée à approuver les comptes.
    """

    _name = "coproerp.cloture"
    _description = "Clôture de l'exercice et annexes comptables"
    _inherit = ["mail.thread"]
    _order = "date_fin desc, id desc"

    name = fields.Char(string="Libellé", compute="_compute_name", store=True)
    budget_id = fields.Many2one(
        "coproerp.budget.annuel", string="Exercice clos", required=True, index=True,
        ondelete="restrict", tracking=True,
    )
    copropriete_id = fields.Many2one(related="budget_id.copropriete_id", store=True, string="Copropriété")
    date_debut = fields.Date(related="budget_id.date_debut", string="Début")
    date_fin = fields.Date(related="budget_id.date_fin", store=True, string="Fin")
    budget_precedent_id = fields.Many2one(
        "coproerp.budget.annuel", string="Exercice précédent approuvé",
        domain="[('copropriete_id', '=', copropriete_id)]",
    )
    budget_en_cours_id = fields.Many2one(
        "coproerp.budget.annuel", string="Budget prévisionnel en cours",
        domain="[('copropriete_id', '=', copropriete_id)]",
        help="Budget de l'exercice qui suit l'exercice clos (déjà voté).",
    )
    budget_a_voter_id = fields.Many2one(
        "coproerp.budget.annuel", string="Budget prévisionnel à voter",
        domain="[('copropriete_id', '=', copropriete_id)]",
        help="Budget soumis au vote de l'assemblée qui approuve les comptes.",
    )
    etat = fields.Selection(
        [("brouillon", "En préparation"), ("cloturee", "Clôturé")],
        string="État", default="brouillon", required=True, readonly=True, copy=False, tracking=True,
    )
    date_cloture = fields.Date(string="Clôturé le", readonly=True, copy=False)
    controles = fields.Text(string="Contrôles", compute="_compute_controles")
    controles_ok = fields.Boolean(compute="_compute_controles")

    @api.depends("budget_id")
    def _compute_name(self):
        for cloture in self:
            cloture.name = "Annexes comptables %s – %s" % (
                cloture.budget_id.exercice or "", cloture.copropriete_id.name or "")

    @api.onchange("budget_id")
    def _onchange_budget_id(self):
        valeurs = self._budgets_voisins(self.budget_id)
        for champ, budget in valeurs.items():
            setattr(self, champ, budget)

    @api.model
    def _budgets_voisins(self, budget):
        Budget = self.env["coproerp.budget.annuel"]
        if not budget or not budget.date_debut or not budget.date_fin:
            return {}

        def suivant(b):
            return Budget.search([
                ("copropriete_id", "=", budget.copropriete_id.id),
                ("date_debut", "=", b.date_fin + timedelta(days=1)),
            ], limit=1) if b else Budget

        precedent = Budget.search([
            ("copropriete_id", "=", budget.copropriete_id.id),
            ("date_fin", "=", budget.date_debut - timedelta(days=1)),
        ], limit=1)
        en_cours = suivant(budget)
        return {
            "budget_precedent_id": precedent,
            "budget_en_cours_id": en_cours,
            "budget_a_voter_id": suivant(en_cours),
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("budget_id"):
                budget = self.env["coproerp.budget.annuel"].browse(vals["budget_id"])
                for champ, valeur in self._budgets_voisins(budget).items():
                    vals.setdefault(champ, valeur.id or False)
        return super().create(vals_list)

    def unlink(self):
        if self.filtered(lambda c: c.etat == "cloturee"):
            raise UserError("Un exercice clôturé ne peut pas être supprimé.")
        return super().unlink()

    # ------------------------------------------------------------------
    # Lecture des écritures
    # ------------------------------------------------------------------
    def _company(self):
        return self.copropriete_id._verifier_dossier()

    def _code(self, ligne, company):
        return ligne.account_id.with_company(company).code or ""

    def _realise(self, budget):
        """Charges et produits réalisés sur l'exercice ``budget``."""
        vide = {
            "courant": {"charges": {}, "produits": {}},
            "travaux": {"charges": {}, "produits": {}},
            "par_cle": defaultdict(dict),
            "par_travaux": defaultdict(lambda: {"charges": {}, "produits": {}}),
            "regularisation": 0.0,
        }
        if not budget or not budget.date_debut or not budget.date_fin:
            return vide
        company = self._company()
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id),
            ("parent_state", "=", "posted"),
            ("date", ">=", budget.date_debut),
            ("date", "<=", budget.date_fin),
        ])
        moves_regul = self.env["coproerp.regularisation"].sudo().search([
            ("budget_id", "=", budget.id), ("etat", "=", "comptabilisee"),
        ]).move_id
        res = vide

        def ajouter(table, code, libelle, montant):
            ancien = table.get(code, (libelle, 0.0))
            table[code] = (ancien[0], ancien[1] + montant)

        for ligne in lignes:
            code = self._code(ligne, company)
            libelle = ligne.account_id.name
            if not code.startswith(("6", "7")):
                continue
            if ligne.move_id in moves_regul:
                res["regularisation"] += -ligne.balance
                continue
            if code.startswith("6"):
                montant = ligne.balance
                categorie = "travaux" if ligne.coproerp_hors_budget else "courant"
                ajouter(res[categorie]["charges"], code, libelle, montant)
                if categorie == "courant":
                    ajouter(res["par_cle"][ligne.coproerp_repartition_id], code, libelle, montant)
                else:
                    ajouter(res["par_travaux"][ligne.coproerp_travaux_id]["charges"], code, libelle, montant)
            elif code.startswith("7"):
                if code.startswith(PRODUITS_EXCLUS):
                    continue
                montant = -ligne.balance
                # Indemnités d'assurance (713) : courantes sauf si elles financent des travaux hors budget
                courant = code.startswith(PRODUITS_COURANTS) or (
                    code.startswith("713") and not ligne.coproerp_hors_budget)
                categorie = "courant" if courant else "travaux"
                ajouter(res[categorie]["produits"], code, libelle, montant)
                if categorie == "travaux":
                    travaux = ligne.move_id.coproerp_appel_id.travaux_id
                    ajouter(res["par_travaux"][travaux]["produits"], code, libelle, montant)
        return res

    @staticmethod
    def _total(table):
        return _arrondi(sum(m for _l, m in table.values()))

    def _budget_total(self, budget):
        if not budget:
            return None
        return _arrondi(sum(budget.ligne_ids.mapped("montant_annuel")) or budget.budget_previsionnel)

    def _budget_par_cle(self, budget):
        resultat = defaultdict(float)
        for ligne in budget.ligne_ids if budget else []:
            resultat[ligne.repartition_id] += ligne.montant_annuel
        return resultat

    # ------------------------------------------------------------------
    # Annexe 1 : état financier après répartition
    # ------------------------------------------------------------------
    def _etat_financier(self, date):
        """Soldes du bilan du syndicat à la date ``date`` (cumul depuis l'origine)."""
        valeurs = defaultdict(float)
        if not date:
            return valeurs
        company = self._company()
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id),
            ("parent_state", "=", "posted"),
            ("date", "<=", date),
        ])
        soldes = defaultdict(float)          # par compte
        coproprietaires = defaultdict(float)  # par copropriétaire (comptes 45)
        for ligne in lignes:
            code = self._code(ligne, company)
            if code.startswith("45") and not code.startswith("459"):
                coproprietaires[ligne.partner_id] += ligne.balance
            else:
                soldes[code] += ligne.balance
        for partner, solde in coproprietaires.items():
            if solde > 0:
                valeurs["creance_45"] += solde
            else:
                valeurs["dette_45"] += -solde
        for code, solde in soldes.items():
            if code.startswith("50"):
                valeurs["tresorerie_50"] += solde
            elif code.startswith("51"):
                valeurs["tresorerie_51"] += solde
            elif code.startswith("53"):
                valeurs["tresorerie_53"] += solde
            elif code.startswith("58"):
                cle = "creance_47" if solde > 0 else "dette_47"
                valeurs[cle] += abs(solde)
            elif code.startswith("102"):
                valeurs["provision_102"] += -solde
            elif code.startswith("1031"):
                valeurs["avance_1031"] += -solde
            elif code.startswith("1032"):
                valeurs["avance_1032"] += -solde
            elif code.startswith("103"):
                valeurs["avance_1033"] += -solde
            elif code.startswith("105"):
                valeurs["fonds_105"] += -solde
            elif code.startswith("106"):
                valeurs["provision_106"] += -solde
            elif code.startswith("131"):
                valeurs["subvention_131"] += -solde
            elif code.startswith(("1", "6", "7")):
                # 12 : solde en attente sur travaux et opérations exceptionnelles,
                # c'est-à-dire le résultat non encore réparti.
                valeurs["attente_12"] += -solde
            elif code.startswith("459"):
                valeurs["creance_459"] += solde
            elif code.startswith("49"):
                valeurs["dette_49"] += -solde
            elif code.startswith("4"):
                prefixe = code[:2]
                groupe = {"40": "40", "41": "42", "42": "42", "43": "42", "44": "42",
                          "46": "46", "47": "47", "48": "48"}.get(prefixe, "47")
                if solde > 0:
                    valeurs["creance_%s" % groupe] += solde
                else:
                    valeurs["dette_%s" % groupe] += -solde
            elif code.startswith("5"):
                # Autres comptes financiers (virements internes…) : comptes d'attente
                cle = "creance_47" if solde > 0 else "dette_47"
                valeurs[cle] += abs(solde)
            else:
                # Comptes hors plan des copropriétés : rattachés au solde en attente
                valeurs["attente_12"] += -solde
        return {cle: _arrondi(v) for cle, v in valeurs.items()}

    @staticmethod
    def _totaux_etat(v):
        tresorerie = v.get("tresorerie_50", 0) + v.get("tresorerie_51", 0) + v.get("tresorerie_53", 0)
        provisions = sum(v.get(k, 0) for k in (
            "provision_102", "avance_1031", "avance_1032", "avance_1033", "fonds_105",
            "provision_106", "subvention_131", "attente_12"))
        creances = sum(v.get(k, 0) for k in (
            "creance_45", "creance_459", "creance_40", "creance_42", "creance_46", "creance_47", "creance_48"))
        dettes = sum(v.get(k, 0) for k in (
            "dette_45", "dette_40", "dette_42", "dette_46", "dette_47", "dette_48", "dette_49"))
        return {
            "tresorerie": _arrondi(tresorerie), "provisions": _arrondi(provisions),
            "creances": _arrondi(creances), "dettes": _arrondi(dettes),
            "actif": _arrondi(tresorerie + creances), "passif": _arrondi(provisions + dettes),
        }

    @staticmethod
    def _sections_annexe1(n, n1, tn, tn1):
        def v(d, cle):
            return d.get(cle, 0.0) if d else None

        def ligne(gauche, droite):
            return {
                "g": gauche and gauche[0], "g_n1": gauche and v(n1, gauche[1]), "g_n": gauche and v(n, gauche[1]),
                "d": droite and droite[0], "d_n1": droite and v(n1, droite[1]), "d_n": droite and v(n, droite[1]),
            }

        gauche1 = [
            ("50 Fonds placés", "tresorerie_50"),
            ("51 Banques, ou fonds disponibles en banque pour le syndicat", "tresorerie_51"),
            ("53 Caisse", "tresorerie_53"),
        ]
        droite1 = [
            ("102 Provisions pour travaux décidés", "provision_102"),
            ("1031 Avances de trésorerie", "avance_1031"),
            ("1032 Avances travaux (art. 18, 6e alinéa, de la loi)", "avance_1032"),
            ("1033 Autres avances", "avance_1033"),
            ("105 Fonds de travaux", "fonds_105"),
            ("106 Autres provisions", "provision_106"),
            ("131 Subventions en instance d'affectation", "subvention_131"),
            ("12 Solde en attente sur travaux et opérations exceptionnelles", "attente_12"),
        ]
        gauche2 = [
            ("45 Copropriétaires – sommes exigibles restant à recevoir", "creance_45"),
            ("459 Copropriétaires – créances douteuses", "creance_459"),
            ("40 Fournisseurs débiteurs", "creance_40"),
            ("42 à 44 Personnel, organismes sociaux, État", "creance_42"),
            ("46 Débiteurs divers", "creance_46"),
            ("47 Comptes d'attente", "creance_47"),
            ("48 Charges payées d'avance", "creance_48"),
        ]
        droite2 = [
            ("45 Copropriétaires – excédents versés", "dette_45"),
            ("40 Fournisseurs", "dette_40"),
            ("42 à 44 Personnel, organismes sociaux, État", "dette_42"),
            ("46 Créditeurs divers", "dette_46"),
            ("47 Comptes d'attente", "dette_47"),
            ("48 Produits encaissés d'avance", "dette_48"),
            ("49 Dépréciation des comptes de tiers", "dette_49"),
        ]

        def appairer(g, d):
            taille = max(len(g), len(d))
            g = g + [None] * (taille - len(g))
            d = d + [None] * (taille - len(d))
            return [ligne(a, b) for a, b in zip(g, d)]

        avec_n1 = bool(n1)
        return [
            {"titre": "I – SITUATION FINANCIÈRE ET TRÉSORERIE",
             "titre_g": "Trésorerie", "titre_d": "Provisions et avances",
             "lignes": appairer(gauche1, droite1),
             "total": {"g": "Trésorerie disponible – Total I", "g_n1": tn1["tresorerie"] if avec_n1 else None,
                       "g_n": tn["tresorerie"], "d": "Total I", "d_n1": tn1["provisions"] if avec_n1 else None,
                       "d_n": tn["provisions"]}},
            {"titre": "II – CRÉANCES ET DETTES",
             "titre_g": "Créances", "titre_d": "Dettes",
             "lignes": appairer(gauche2, droite2),
             "total": {"g": "Total II", "g_n1": tn1["creances"] if avec_n1 else None, "g_n": tn["creances"],
                       "d": "Total II", "d_n1": tn1["dettes"] if avec_n1 else None, "d_n": tn["dettes"]}},
        ]

    def fmt(self, valeur):
        """Montant au format français pour les annexes (vide si non applicable)."""
        if valeur is None or valeur is False:
            return ""
        texte = "{:,.2f}".format(valeur + 0.0).replace(",", "\u00a0").replace(".", ",")
        return "-" if texte in ("0,00", "-0,00") else texte

    # ------------------------------------------------------------------
    # Annexe 5 : travaux votés non clôturés
    # ------------------------------------------------------------------
    def _travaux_non_clotures(self):
        self.ensure_one()
        company = self._company()
        travaux = self.env["coproerp.travaux"].sudo().search([
            ("copropriete_id", "=", self.copropriete_id.id),
            ("etat", "not in", ("projet", "cloture", "annule")),
            ("date_vote", "<=", self.date_fin),
        ], order="date_vote, id")
        MoveLine = self.env["account.move.line"].sudo()
        lignes = []
        for operation in travaux:
            charges = MoveLine.search([
                ("company_id", "=", company.id), ("parent_state", "=", "posted"),
                ("date", "<=", self.date_fin), ("coproerp_travaux_id", "=", operation.id),
            ]).filtered(lambda l: self._code(l, company).startswith("6"))
            produits = MoveLine.search([
                ("company_id", "=", company.id), ("parent_state", "=", "posted"),
                ("date", "<=", self.date_fin),
                ("move_id.coproerp_appel_id.travaux_id", "=", operation.id),
            ]).filtered(lambda l: self._code(l, company).startswith("7")
                        and not self._code(l, company).startswith(PRODUITS_EXCLUS))
            depenses = _arrondi(sum(charges.mapped("balance")))
            appels = _arrondi(-sum(produits.mapped("balance")))
            lignes.append({
                "travaux": operation,
                "montant_vote": _arrondi(operation.montant_vote),
                "depenses": depenses,
                "appels": appels,
                "solde": _arrondi(appels - depenses),
            })
        return lignes

    # ------------------------------------------------------------------
    # Données de l'ensemble des annexes
    # ------------------------------------------------------------------
    def donnees_annexes(self):
        self.ensure_one()
        n1 = self._realise(self.budget_precedent_id)
        n = self._realise(self.budget_id)
        budgets = {
            "n1": self.budget_precedent_id,
            "n": self.budget_id,
            "en_cours": self.budget_en_cours_id,
            "a_voter": self.budget_a_voter_id,
        }

        # Budget détaillé par nature (facultatif) : None si le budget n'est pas détaillé
        details = {k: (b.budget_par_nature() if b and b.detail_ids else None) for k, b in budgets.items()}
        libelles_natures = {nat.code: nat.name for nat in self.env["coproerp.nature.depense"].with_context(
            active_test=False).search([])}

        def budget_code(code, cle=None):
            valeurs = {}
            for k, detail in details.items():
                if detail is None:
                    valeurs[k] = None
                elif cle is None:
                    valeurs[k] = _arrondi(detail[1].get(code, 0.0))
                else:
                    valeurs[k] = _arrondi(detail[0].get((cle, code), 0.0))
            return valeurs

        def somme_budgets(lignes):
            return {k: (_arrondi(sum(l["budget"][k] or 0.0 for l in lignes)) if details[k] is not None else None)
                    for k in budgets}

        def tableau(cat, sens):
            codes = set(n1[cat][sens]) | set(n[cat][sens])
            if cat == "courant" and sens == "charges":
                for detail in details.values():
                    if detail is not None:
                        codes |= set(detail[1])
            lignes = []
            for code in sorted(codes):
                trouve = n[cat][sens].get(code) or n1[cat][sens].get(code)
                libelle = trouve[0] if trouve else libelles_natures.get(code, code)
                lignes.append({
                    "code": code, "libelle": libelle,
                    "n1": _arrondi(n1[cat][sens].get(code, ("", 0.0))[1]),
                    "n": _arrondi(n[cat][sens].get(code, ("", 0.0))[1]),
                    "budget": budget_code(code) if (cat, sens) == ("courant", "charges")
                    else {k: None for k in budgets},
                })
            return lignes

        def par_classe(lignes):
            groupes = []
            for prefixe in sorted({l["code"][:2] for l in lignes}):
                membres = [l for l in lignes if l["code"][:2] == prefixe]
                groupes.append({
                    "classe": prefixe, "libelle": CLASSES_CHARGES.get(prefixe, ""),
                    "lignes": membres,
                    "n1": _arrondi(sum(l["n1"] for l in membres)),
                    "n": _arrondi(sum(l["n"] for l in membres)),
                    "budget": somme_budgets(membres),
                })
            return groupes

        # Annexe 2
        charges_courantes = tableau("courant", "charges")
        produits_courants = tableau("courant", "produits")
        charges_travaux = tableau("travaux", "charges")
        produits_travaux = tableau("travaux", "produits")
        budget_totaux = {cle: self._budget_total(b) for cle, b in budgets.items()}
        annexe2 = {
            "courant": {
                "charges": par_classe(charges_courantes),
                "produits": produits_courants,
                "total_charges": {"n1": self._total(n1["courant"]["charges"]),
                                  "n": self._total(n["courant"]["charges"])},
                "total_produits": {"n1": self._total(n1["courant"]["produits"]),
                                   "n": self._total(n["courant"]["produits"])},
            },
            "travaux": {
                "charges": par_classe(charges_travaux),
                "produits": produits_travaux,
                "total_charges": {"n1": self._total(n1["travaux"]["charges"]),
                                  "n": self._total(n["travaux"]["charges"])},
                "total_produits": {"n1": self._total(n1["travaux"]["produits"]),
                                   "n": self._total(n["travaux"]["produits"])},
            },
            "budget": budget_totaux,
            "budget_non_detaille": {
                k: (_arrondi((budget_totaux[k] or 0.0) - sum(details[k][1].values()))
                    if details[k] is not None else None) for k in budgets},
            "regularisation": {"n1": _arrondi(n1["regularisation"]), "n": _arrondi(n["regularisation"])},
        }
        for partie in ("courant", "travaux"):
            p = annexe2[partie]
            p["solde"] = {k: _arrondi(p["total_charges"][k] - p["total_produits"][k]) for k in ("n1", "n")}

        # Annexe 3 : opérations courantes par clé de répartition
        budgets_cles = {cle: self._budget_par_cle(b) for cle, b in budgets.items()}
        cles = set(n1["par_cle"]) | set(n["par_cle"])
        for valeurs in budgets_cles.values():
            cles |= set(valeurs)
        annexe3 = []
        for cle in sorted(cles, key=lambda c: (not c, c.name or "")):
            codes = set(n1["par_cle"].get(cle, {})) | set(n["par_cle"].get(cle, {}))
            for detail in details.values():
                if detail is not None:
                    codes |= {code for (c, code) in detail[0] if c == cle}
            lignes = []
            for code in sorted(codes):
                trouve = n["par_cle"].get(cle, {}).get(code) or n1["par_cle"].get(cle, {}).get(code)
                lignes.append({
                    "code": code,
                    "libelle": trouve[0] if trouve else libelles_natures.get(code, code),
                    "n1": _arrondi(n1["par_cle"].get(cle, {}).get(code, ("", 0.0))[1]),
                    "n": _arrondi(n["par_cle"].get(cle, {}).get(code, ("", 0.0))[1]),
                    "budget": budget_code(code, cle),
                })
            annexe3.append({
                "cle": cle,
                "libelle": cle.name if cle else "Charges sans clé de répartition",
                "lignes": lignes,
                "n1": _arrondi(sum(l["n1"] for l in lignes)),
                "n": _arrondi(sum(l["n"] for l in lignes)),
                "budget": {k: (_arrondi(v.get(cle, 0.0)) if budgets[k] else None)
                           for k, v in budgets_cles.items()},
            })
        total3 = {
            "n1": _arrondi(sum(c["n1"] for c in annexe3)),
            "n": _arrondi(sum(c["n"] for c in annexe3)),
            "budget": {k: (_arrondi(sum((c["budget"][k] or 0.0) for c in annexe3)) if budgets[k] else None)
                       for k in budgets},
        }

        # Annexe 4 : travaux et opérations exceptionnelles, par opération
        operations = set(n1["par_travaux"]) | set(n["par_travaux"])
        annexe4 = []
        for operation in sorted(operations, key=lambda t: (not t, t.reference or "")):
            def tab(sens):
                a = n1["par_travaux"].get(operation, {"charges": {}, "produits": {}})[sens]
                b = n["par_travaux"].get(operation, {"charges": {}, "produits": {}})[sens]
                return [{"code": c, "libelle": (b.get(c) or a.get(c))[0],
                         "n1": _arrondi(a.get(c, ("", 0.0))[1]), "n": _arrondi(b.get(c, ("", 0.0))[1])}
                        for c in sorted(set(a) | set(b))]
            charges, produits = tab("charges"), tab("produits")
            annexe4.append({
                "travaux": operation,
                "libelle": ("%s – %s" % (operation.reference, operation.name)) if operation
                else "Opérations exceptionnelles non rattachées à une opération de travaux",
                "charges": charges, "produits": produits,
                "total_charges": {k: _arrondi(sum(l[k] for l in charges)) for k in ("n1", "n")},
                "total_produits": {k: _arrondi(sum(l[k] for l in produits)) for k in ("n1", "n")},
            })

        # Annexe 1
        date_precedente = self.date_debut - timedelta(days=1) if self.date_debut else False
        etat_n = self._etat_financier(self.date_fin)
        etat_n1 = self._etat_financier(date_precedente) if self.budget_precedent_id else {}
        totaux_n = self._totaux_etat(etat_n)
        totaux_n1 = self._totaux_etat(etat_n1)
        annexe5 = self._travaux_non_clotures()
        return {
            "cloture": self,
            "copro": self.copropriete_id.sudo(),
            "budgets": budgets,
            "projet": self.etat != "cloturee",
            "annexe1": {"n": etat_n, "n1": etat_n1,
                        "totaux_n": totaux_n, "totaux_n1": totaux_n1,
                        "sections": self._sections_annexe1(etat_n, etat_n1, totaux_n, totaux_n1),
                        "date_n": self.date_fin, "date_n1": date_precedente},
            "annexe2": annexe2,
            "annexe3": {"cles": annexe3, "total": total3},
            "annexe4": annexe4,
            "annexe5": {"lignes": annexe5,
                        "total": {k: _arrondi(sum(l[k] for l in annexe5))
                                  for k in ("montant_vote", "depenses", "appels", "solde")}},
        }

    # ------------------------------------------------------------------
    # Contrôles et clôture
    # ------------------------------------------------------------------
    def _verifications(self):
        """Liste de (bloquant, message)."""
        self.ensure_one()
        resultat = []
        budget = self.budget_id
        if not self.copropriete_id.company_id:
            return [(True, "La copropriété n'a pas de dossier comptable.")]
        regul = self.env["coproerp.regularisation"].search([
            ("budget_id", "=", budget.id), ("etat", "=", "comptabilisee")], limit=1)
        if not regul:
            resultat.append((True, "La régularisation des charges de l'exercice n'est pas comptabilisée."))
        appels = self.env["coproerp.appel.charge"].search([
            ("copropriete_id", "=", self.copropriete_id.id),
            ("date_echeance", ">=", budget.date_debut), ("date_echeance", "<=", budget.date_fin),
            ("etat_comptable", "=", "projet"),
        ])
        if appels:
            resultat.append((True, "%d appel(s) de fonds de l'exercice ne sont pas comptabilisés." % len(appels)))
        factures = self.env["coproerp.depense"].search([
            ("copropriete_id", "=", self.copropriete_id.id),
            ("date_facture", ">=", budget.date_debut), ("date_facture", "<=", budget.date_fin),
            ("etat", "=", "brouillon"),
        ])
        if factures:
            resultat.append((True, "%d facture(s) fournisseurs de l'exercice sont encore en brouillon." % len(factures)))
        company = self._company()
        brouillons = self.env["account.move"].sudo().search_count([
            ("company_id", "=", company.id), ("state", "=", "draft"), ("date", "<=", budget.date_fin),
        ])
        if brouillons:
            resultat.append((True, "%d écriture(s) comptable(s) en brouillon datées de l'exercice : "
                                   "validez-les ou supprimez-les." % brouillons))
        compte_705 = self.copropriete_id._compte(self.copropriete_id.compte_produit_fonds)
        solde_705 = sum(self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id), ("account_id", "=", compte_705.id),
            ("parent_state", "=", "posted"), ("date", "<=", budget.date_fin),
        ]).mapped("balance"))
        if abs(solde_705) > 0.005:
            resultat.append((True, "Le fonds de travaux de l'exercice n'est pas mis en réserve "
                                   "(compte 705 non soldé) : utilisez « Mettre en réserve le fonds de travaux »."))
        totaux = self._totaux_etat(self._etat_financier(budget.date_fin))
        if abs(totaux["actif"] - totaux["passif"]) > 0.01:
            resultat.append((True, "L'état financier (annexe 1) n'est pas équilibré : %.2f / %.2f."
                                   % (totaux["actif"], totaux["passif"])))
        return resultat

    def _compute_controles(self):
        for cloture in self:
            if not cloture.budget_id:
                cloture.controles, cloture.controles_ok = False, False
                continue
            try:
                verifs = cloture._verifications()
            except UserError as erreur:
                verifs = [(True, str(erreur))]
            cloture.controles_ok = not any(b for b, _m in verifs)
            cloture.controles = "\n".join("• " + m for _b, m in verifs) or "Tous les contrôles sont satisfaits."

    def action_cloturer(self):
        for cloture in self.filtered(lambda c: c.etat == "brouillon"):
            bloquants = [m for b, m in cloture._verifications() if b]
            if bloquants:
                raise UserError("La clôture est impossible :\n- " + "\n- ".join(bloquants))
            company = cloture._company()
            # Verrouillage des écritures de l'exercice clos
            if not company.fiscalyear_lock_date or company.fiscalyear_lock_date < cloture.date_fin:
                company.sudo().fiscalyear_lock_date = cloture.date_fin
            cloture.write({"etat": "cloturee", "date_cloture": fields.Date.context_today(cloture)})
        return True

    def action_imprimer_annexes(self):
        self.ensure_one()
        self._company()
        return self.env.ref("coproerp_cloture.action_report_annexes").report_action(self)
