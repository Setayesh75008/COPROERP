from odoo import Command, api, fields, models
from odoo.exceptions import UserError

# Correspondance type d'appel -> (compte du copropriétaire, compte de contrepartie)
# Les numéros sont paramétrables sur chaque copropriété (onglet Comptabilité).
COMPTES_PAR_TYPE = {
    "budget_courant": ("compte_copro_budget", "compte_produit_budget"),
    "fonds_travaux": ("compte_copro_fonds", "compte_produit_fonds"),
    "appel_exceptionnel": ("compte_copro_travaux", "compte_produit_travaux"),
    "hors_budget": ("compte_copro_travaux", "compte_produit_travaux"),
    "avance": ("compte_copro_avances", "compte_avances"),
    "autre": ("compte_copro_budget", "compte_produit_budget"),
}

JOURNAUX = {"appels": "APF", "banque": "BQ", "achats": "ACH", "od": "OD"}


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    company_id = fields.Many2one(
        "res.company",
        string="Dossier comptable",
        readonly=True,
        copy=False,
        help="Comptabilité propre au syndicat (société Odoo dédiée).",
    )

    # --- Numéros de comptes utilisés par les écritures automatiques ---
    compte_copro_budget = fields.Char("Copropriétaires – budget", default="450010", required=True)
    compte_copro_travaux = fields.Char("Copropriétaires – travaux", default="450020", required=True)
    compte_copro_avances = fields.Char("Copropriétaires – avances", default="450030", required=True)
    compte_copro_fonds = fields.Char("Copropriétaires – fonds de travaux", default="450050", required=True)
    compte_produit_budget = fields.Char("Provisions sur opérations courantes", default="701000", required=True)
    compte_produit_travaux = fields.Char("Provisions sur travaux", default="702000", required=True)
    compte_produit_fonds = fields.Char("Allocations de fonds de travaux", default="705000", required=True)
    compte_avances = fields.Char("Avances (fonds de roulement)", default="103100", required=True)
    compte_reserve_fonds = fields.Char("Fonds de travaux (réserve)", default="105000", required=True)

    # ------------------------------------------------------------------
    # Création du dossier comptable
    # ------------------------------------------------------------------
    def action_creer_dossier_comptable(self):
        for copro in self:
            if copro.company_id:
                raise UserError("La copropriété %s a déjà un dossier comptable." % copro.name)
            copro._creer_dossier_comptable()
        return True

    def _creer_dossier_comptable(self):
        self.ensure_one()
        Company = self.env["res.company"].sudo()
        budget = self.env["coproerp.budget.annuel"].search(
            [("copropriete_id", "=", self.id)], order="date_debut desc", limit=1
        )
        fin = budget.date_fin if budget else False
        company = Company.create({
            "name": "SDC %s" % self.name,
            "currency_id": self.env.ref("base.EUR").id,
            "country_id": self.env.ref("base.fr").id,
            "street": self.street or False,
            "zip": self.zip or False,
            "city": self.city or False,
            "company_registry": self.siret or False,
            "fiscalyear_last_day": fin.day if fin else 31,
            "fiscalyear_last_month": str(fin.month) if fin else "12",
            # Protège le dossier contre le chargement automatique du plan
            # comptable général français (voir coproerp_plan_comptable).
            "coproerp_dossier_copro": True,
        })
        # Les utilisateurs internes du cabinet accèdent au nouveau dossier.
        utilisateurs = self.env["res.users"].sudo().search([
            ("share", "=", False),
            ("company_ids", "in", self.env.company.ids),
        ]) | self.env.user
        utilisateurs.write({"company_ids": [Command.link(company.id)]})

        self.env["account.chart.template"].sudo().try_loading("copro_fr", company, install_demo=False)
        self.company_id = company
        self._configurer_dossier_comptable(company)
        return company

    def _configurer_dossier_comptable(self, company):
        """Réglages du dossier après chargement du plan comptable."""
        self.ensure_one()
        company = company.sudo()
        company.restrictive_audit_trail = True
        journaux = self.env["account.journal"].sudo().search([
            ("company_id", "=", company.id),
            ("code", "in", list(JOURNAUX.values())),
        ])
        # Inaltérabilité : les écritures validées sont scellées (chaînage).
        journaux.write({"restrict_mode_hash_table": True})
        banque = journaux.filtered(lambda j: j.code == JOURNAUX["banque"])
        if banque and self.banque_iban and not banque.bank_account_id:
            Banque = self.env["res.partner.bank"].sudo().with_context(active_test=False)
            iban = self.banque_iban.replace(" ", "").upper()
            compte_bancaire = Banque.search([
                ("partner_id", "=", company.partner_id.id),
                ("sanitized_acc_number", "=", iban),
            ], limit=1) or Banque.create({
                "acc_number": self.banque_iban,
                "partner_id": company.partner_id.id,
            })
            banque.bank_account_id = compte_bancaire

    # ------------------------------------------------------------------
    # Réparation d'un dossier dont le plan comptable a été remplacé
    # ------------------------------------------------------------------
    dossier_a_reparer = fields.Boolean(compute="_compute_dossier_a_reparer")

    def _compute_dossier_a_reparer(self):
        for copro in self:
            copro.dossier_a_reparer = bool(
                copro.company_id and copro.company_id.sudo().chart_template != "copro_fr"
            )

    def action_reparer_dossier_comptable(self):
        for copro in self.filtered("dossier_a_reparer"):
            company = copro.company_id.sudo()
            if self.env["account.move"].sudo().search_count([("company_id", "=", company.id)]):
                raise UserError(
                    "Le dossier comptable de %s contient déjà des écritures : il ne peut "
                    "pas être réparé automatiquement." % copro.name
                )
            company.coproerp_dossier_copro = True
            self.env["account.chart.template"].sudo().try_loading("copro_fr", company, install_demo=False)
            copro._configurer_dossier_comptable(company)
        return True

    # ------------------------------------------------------------------
    # Outils comptables
    # ------------------------------------------------------------------
    def _verifier_dossier(self):
        self.ensure_one()
        if not self.company_id:
            raise UserError(
                "La copropriété %s n'a pas de dossier comptable : créez-le depuis sa "
                "fiche (onglet Comptabilité)." % self.name
            )
        if self.company_id.sudo().chart_template != "copro_fr":
            raise UserError(
                "Le dossier comptable de %s n'a pas le plan comptable des copropriétés. "
                "Fiche de la copropriété, onglet Comptabilité : cliquez sur "
                "« Réparer le dossier comptable »." % self.name
            )
        # sudo : la fiche de la société doit rester lisible (devise, etc.)
        # même si l'utilisateur ne l'a pas cochée dans le sélecteur de sociétés.
        return self.company_id.sudo()

    def _compte(self, code):
        company = self._verifier_dossier()
        # sudo : aussi appelé depuis l'extranet (utilisateurs du portail)
        Account = self.env["account.account"].sudo().with_company(company)
        compte = Account.search(
            [*Account._check_company_domain(company), ("code", "=", code)], limit=1
        )
        if not compte:
            raise UserError(
                "Le compte %s n'existe pas dans le dossier comptable de %s." % (code, self.name)
            )
        return compte

    def _comptes_par_type(self, type_appel):
        champ_tiers, champ_contrepartie = COMPTES_PAR_TYPE.get(type_appel, COMPTES_PAR_TYPE["autre"])
        return self._compte(self[champ_tiers]), self._compte(self[champ_contrepartie])

    def _comptes_coproprietaires(self):
        return (
            self._compte(self.compte_copro_budget)
            | self._compte(self.compte_copro_travaux)
            | self._compte(self.compte_copro_avances)
            | self._compte(self.compte_copro_fonds)
        )

    def _journal(self, cle):
        company = self._verifier_dossier()
        journal = self.env["account.journal"].with_company(company).search(
            [("company_id", "=", company.id), ("code", "=", JOURNAUX[cle])], limit=1
        )
        if not journal:
            raise UserError("Journal %s introuvable dans le dossier de %s." % (JOURNAUX[cle], self.name))
        return journal

    def _lignes_coproprietaires(self, partner_ids=None, date_max=None, date_min_exclue=None):
        """Lignes comptables validées des comptes copropriétaires (450xxx)."""
        self.ensure_one()
        company = self.company_id
        domaine = [
            ("company_id", "=", company.id),
            ("account_id", "in", self._comptes_coproprietaires().ids),
            ("parent_state", "=", "posted"),
        ]
        if partner_ids is not None:
            domaine.append(("partner_id", "in", list(partner_ids)))
        if date_max:
            domaine.append(("date", "<=", date_max))
        if date_min_exclue:
            domaine.append(("date", ">", date_min_exclue))
        return self.env["account.move.line"].sudo().search(domaine, order="date, move_id, id")

    # ------------------------------------------------------------------
    # Relevé de compte d'un copropriétaire (avis d'appel)
    # ------------------------------------------------------------------
    def releve_compte(self, personne, date_precedent, date_fin):
        """Solde au précédent relevé, mouvements, nouveau solde.

        Solde positif = somme due par le copropriétaire.
        """
        self.ensure_one()
        anterieures = self._lignes_coproprietaires(personne.ids, date_max=date_precedent) if date_precedent else []
        solde_precedent = sum(l.debit - l.credit for l in anterieures)
        lignes = self._lignes_coproprietaires(personne.ids, date_max=date_fin, date_min_exclue=date_precedent)
        mouvements = [{
            "date": l.date,
            "libelle": l.name or l.move_id.ref or "",
            "debit": l.debit,
            "credit": l.credit,
            "move_id": l.move_id.id,
        } for l in lignes]
        solde = solde_precedent + sum(m["debit"] - m["credit"] for m in mouvements)
        return {
            "date_precedent": date_precedent,
            "solde_precedent": round(solde_precedent, 2),
            "mouvements": mouvements,
            "solde": round(solde, 2),
            "date_solde": date_fin,
        }

    def fonds_du_coproprietaire(self, personne):
        """Fonds de roulement (avances) et fonds de travaux cumulés, au crédit du copropriétaire."""
        self.ensure_one()
        company = self.company_id
        MoveLine = self.env["account.move.line"].sudo()

        def solde_crediteur(codes):
            comptes = self.env["account.account"]
            for code in codes:
                comptes |= self._compte(code)
            lignes = MoveLine.search([
                ("company_id", "=", company.id),
                ("account_id", "in", comptes.ids),
                ("partner_id", "=", personne.id),
                ("parent_state", "=", "posted"),
            ])
            return round(sum(l.credit - l.debit for l in lignes), 2)

        return {
            "fonds_roulement": solde_crediteur([self.compte_avances]),
            "fonds_travaux": solde_crediteur([self.compte_produit_fonds, self.compte_reserve_fonds]),
        }

    # ------------------------------------------------------------------
    # Extranet : situation réelle issue de la comptabilité
    # ------------------------------------------------------------------
    def _extranet_personnes_autorisees(self, partner_ids):
        """Défense en profondeur : les écritures sont lues en sudo, on limite donc
        explicitement ce qu'un utilisateur du portail peut obtenir."""
        self.ensure_one()
        user = self.env.user
        if not user._is_portal():
            return partner_ids
        personnes = user.partner_id | user.partner_id.commercial_partner_id
        est_cs = self.env["coproerp.cs.mandat"].sudo().search_count([
            ("copropriete_id", "=", self.id),
            ("personne_id", "in", personnes.ids),
            ("en_cours", "=", True),
        ])
        if est_cs:
            return partner_ids
        if partner_ids is None:
            return personnes.ids
        return [pid for pid in partner_ids if pid in personnes.ids]

    def _extranet_mouvements(self, partner_ids=None):
        if not self.company_id:
            return super()._extranet_mouvements(partner_ids)
        partner_ids = self._extranet_personnes_autorisees(partner_ids)
        mouvements = []
        for ligne in self._lignes_coproprietaires(partner_ids):
            mouvements.append({
                "date": ligne.date,
                "libelle": ligne.name or ligne.move_id.ref or "",
                "debit": ligne.debit,
                "credit": ligne.credit,
                "personne_id": ligne.partner_id.id,
                "appel_id": ligne.move_id.coproerp_appel_id.id or False,
            })
        return mouvements

    def _extranet_depenses(self):
        if not self.company_id:
            return super()._extranet_depenses()
        company = self.company_id
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "in", ("expense", "expense_other")),
        ], order="account_id, date, id")
        return [{
            "compte": l.account_id.with_company(company).code,
            "libelle_compte": l.account_id.name,
            "date": l.date,
            "libelle": l.name or l.move_id.ref or (l.partner_id.name or ""),
            "debit": l.debit,
            "credit": l.credit,
        } for l in lignes]

    # ------------------------------------------------------------------
    # Mise en réserve du fonds de travaux (clôture)
    # ------------------------------------------------------------------
    def _mettre_en_reserve_fonds_travaux(self, date_cloture):
        """Solde le compte 705 au profit du compte 105, copropriétaire par
        copropriétaire (pour conserver le cumul par copropriétaire)."""
        self.ensure_one()
        company = self._verifier_dossier()
        # Travaille dans la société de la copropriété, même si l'utilisateur
        # ne l'a pas cochée dans le sélecteur de sociétés.
        self = self.with_company(company)
        compte_705 = self._compte(self.compte_produit_fonds)
        compte_105 = self._compte(self.compte_reserve_fonds)
        lignes = self.env["account.move.line"].search([
            ("company_id", "=", company.id),
            ("account_id", "=", compte_705.id),
            ("parent_state", "=", "posted"),
            ("date", "<=", date_cloture),
        ])
        soldes = {}
        for ligne in lignes:
            soldes[ligne.partner_id] = soldes.get(ligne.partner_id, 0.0) + ligne.credit - ligne.debit
        arrondi = company.currency_id.round
        commandes = []
        for partenaire, solde in soldes.items():
            solde = arrondi(solde)
            if not solde:
                continue
            libelle = "Mise en réserve du fonds de travaux"
            commandes += [
                Command.create({"account_id": compte_705.id, "partner_id": partenaire.id,
                                "name": libelle, "debit": solde if solde > 0 else 0.0,
                                "credit": -solde if solde < 0 else 0.0}),
                Command.create({"account_id": compte_105.id, "partner_id": partenaire.id,
                                "name": libelle, "credit": solde if solde > 0 else 0.0,
                                "debit": -solde if solde < 0 else 0.0}),
            ]
        if not commandes:
            raise UserError("Le compte %s est déjà soldé à cette date." % compte_705.code)
        move = self.env["account.move"].with_company(company).create({
            "move_type": "entry",
            "journal_id": self._journal("od").id,
            "date": date_cloture,
            "ref": "Mise en réserve du fonds de travaux au %s" % date_cloture.strftime("%d/%m/%Y"),
            "line_ids": commandes,
        })
        move.action_post()
        return move

    def action_ouvrir_comptabilite(self):
        self.ensure_one()
        company = self._verifier_dossier()
        return {
            "type": "ir.actions.act_window",
            "name": "Écritures – %s" % self.name,
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("company_id", "=", company.id)],
            "context": {"allowed_company_ids": [company.id] + self.env.companies.ids},
        }
