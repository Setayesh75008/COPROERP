from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

COMPTE_ATTENTE = "471000"      # contrepartie des factures reprises
COMPTE_FOURNISSEURS = "401000"


class Reprise(models.Model):
    """Reprise des soldes d'une copropriété à une date donnée (écriture d'à-nouveaux)."""

    _name = "coproerp.reprise"
    _description = "Reprise des soldes d'une copropriété"
    _inherit = ["mail.thread"]
    _order = "date_reprise desc, id desc"

    name = fields.Char(string="Libellé", compute="_compute_name", store=True)
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="restrict", tracking=True)
    date_reprise = fields.Date(
        string="Date de reprise", required=True, tracking=True,
        help="Date à laquelle les soldes sont arrêtés, en principe la veille du premier exercice géré dans "
             "CoproERP (ex. : 31/12/2025 pour un premier exercice commençant le 01/01/2026).",
    )
    origine = fields.Char(string="Source des soldes", help="Ex. : état financier du syndic précédent au 31/12/2025.")
    solde_banque = fields.Float(
        string="Solde du compte bancaire séparé", digits=(16, 2), tracking=True,
        help="Solde du relevé bancaire à la date de reprise (négatif en cas de découvert).",
    )
    coproprietaire_ids = fields.One2many("coproerp.reprise.coproprietaire", "reprise_id", string="Copropriétaires")
    facture_ids = fields.One2many("coproerp.reprise.facture", "reprise_id", string="Factures fournisseurs à payer")
    autre_ids = fields.One2many("coproerp.reprise.autre", "reprise_id", string="Autres soldes")
    etat = fields.Selection(
        [("brouillon", "En préparation"), ("validee", "Comptabilisée"), ("annulee", "Annulée")],
        string="État", default="brouillon", required=True, readonly=True, copy=False, tracking=True,
    )
    move_id = fields.Many2one("account.move", string="Écriture d'à-nouveaux", readonly=True, copy=False)
    move_annulation_id = fields.Many2one("account.move", string="Écriture d'annulation", readonly=True, copy=False)
    depense_ids = fields.One2many("coproerp.depense", "reprise_id", string="Factures reprises")

    total_debit = fields.Float(string="Total débit", compute="_compute_totaux", digits=(16, 2))
    total_credit = fields.Float(string="Total crédit", compute="_compute_totaux", digits=(16, 2))
    total_factures = fields.Float(string="Factures à payer", compute="_compute_totaux", digits=(16, 2))
    ecart = fields.Float(
        string="Écart à expliquer", compute="_compute_totaux", digits=(16, 2),
        help="Doit être nul : ce que possède le syndicat (banque, sommes dues par les copropriétaires…) doit "
             "être égal à ce qu'il doit (avances, fonds de travaux, fournisseurs, autres soldes).",
    )

    @api.depends("copropriete_id", "date_reprise")
    def _compute_name(self):
        for reprise in self:
            reprise.name = "Reprise des soldes au %s – %s" % (
                reprise.date_reprise.strftime("%d/%m/%Y") if reprise.date_reprise else "…",
                reprise.copropriete_id.name or "")

    @api.depends("solde_banque", "coproprietaire_ids.solde", "coproprietaire_ids.fonds_travaux",
                 "coproprietaire_ids.avance", "facture_ids.montant", "autre_ids.debit", "autre_ids.credit")
    def _compute_totaux(self):
        for reprise in self:
            debit, credit = reprise._sommes()
            factures = round(sum(reprise.facture_ids.mapped("montant")), 2)
            reprise.total_debit = round(debit, 2)
            reprise.total_credit = round(credit + factures, 2)
            reprise.total_factures = factures
            reprise.ecart = round(debit - credit - factures, 2)

    def _sommes(self):
        """Débits et crédits de l'écriture d'à-nouveaux, hors factures."""
        self.ensure_one()
        debit = credit = 0.0
        if self.solde_banque >= 0:
            debit += self.solde_banque
        else:
            credit -= self.solde_banque
        for ligne in self.coproprietaire_ids:
            if ligne.solde >= 0:
                debit += ligne.solde
            else:
                credit -= ligne.solde
            credit += ligne.fonds_travaux + ligne.avance
        for ligne in self.autre_ids:
            debit += ligne.debit
            credit += ligne.credit
        return debit, credit

    @api.constrains("date_reprise")
    def _check_date(self):
        for reprise in self:
            if reprise.date_reprise and reprise.date_reprise > fields.Date.context_today(reprise):
                raise ValidationError("La date de reprise ne peut pas être dans le futur.")

    def write(self, vals):
        if self.filtered(lambda r: r.etat != "brouillon") and set(vals) - {"origine", "message_main_attachment_id"}:
            raise UserError("Une reprise comptabilisée ne peut plus être modifiée : annulez-la et refaites-la.")
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda r: r.etat == "validee"):
            raise UserError("Une reprise comptabilisée ne peut pas être supprimée : annulez-la.")
        return super().unlink()

    # ------------------------------------------------------------------
    def action_charger_coproprietaires(self):
        """Ajoute une ligne (à zéro) pour chaque copropriétaire destinataire des appels."""
        for reprise in self:
            if reprise.etat != "brouillon":
                raise UserError("La reprise est déjà comptabilisée.")
            presents = reprise.coproprietaire_ids.personne_id
            lots = self.env["coproerp.lot"].search([("copropriete_id", "=", reprise.copropriete_id.id)])
            personnes = self.env["res.partner"]
            erreurs = []
            for lot in lots:
                if lot.propriete_syndicat:
                    continue
                partner, erreur = lot._destinataire_appels(reprise.date_reprise)
                if erreur:
                    erreurs.append(erreur)
                personnes |= partner
            if erreurs and not personnes:
                raise UserError("\n".join(erreurs))
            super(Reprise, reprise).write({"coproprietaire_ids": [
                Command.create({"personne_id": p.id}) for p in (personnes - presents).sorted("name")]})
        return True

    def action_comptabiliser(self):
        for reprise in self.filtered(lambda r: r.etat == "brouillon"):
            copro = reprise.copropriete_id
            company = copro._verifier_dossier()
            if not float_is_zero(reprise.ecart, precision_digits=2):
                raise UserError(
                    "La reprise n'est pas équilibrée : écart de %.2f €.\nVérifiez les soldes saisis ou ajoutez la "
                    "ligne manquante dans « Autres soldes » (provisions pour travaux, solde en attente sur travaux, "
                    "comptes de tiers…)." % reprise.ecart)
            if self.search_count([("copropriete_id", "=", copro.id), ("etat", "=", "validee"),
                                  ("id", "!=", reprise.id)]):
                raise UserError("Une reprise des soldes est déjà comptabilisée pour cette copropriété.")
            commandes = reprise._lignes_ecriture(copro, company)
            if not commandes:
                raise UserError("Aucun solde à reprendre.")
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry",
                "journal_id": copro._journal("od").id,
                "date": reprise.date_reprise,
                "ref": reprise.name,
                "line_ids": commandes,
            })
            move.action_post()
            depenses = reprise._creer_factures(copro)
            super(Reprise, reprise).write({"move_id": move.id, "etat": "validee"})
            reprise.message_post(body="Reprise comptabilisée : %d copropriétaire(s), %d facture(s) à payer." % (
                len(reprise.coproprietaire_ids), len(depenses)))
        return True

    def _lignes_ecriture(self, copro, company):
        libelle = "Reprise du solde au %s" % self.date_reprise.strftime("%d/%m/%Y")
        commandes = []

        def ligne(compte, montant, partner=None, nom=libelle, cle=None):
            if float_is_zero(montant, precision_digits=2):
                return
            vals = {
                "account_id": compte.id,
                "name": nom,
                "debit": round(montant, 2) if montant > 0 else 0.0,
                "credit": round(-montant, 2) if montant < 0 else 0.0,
            }
            if partner:
                vals["partner_id"] = partner.id
            commandes.append(Command.create(vals))

        journal_banque = copro._journal("banque")
        if not journal_banque.default_account_id:
            raise UserError("Le journal de banque n'a pas de compte (512).")
        ligne(journal_banque.default_account_id, self.solde_banque, nom="Solde bancaire au %s" % self.date_reprise.strftime("%d/%m/%Y"))
        compte_copro = copro._compte(copro.compte_copro_budget)
        compte_fonds = copro._compte(copro.compte_reserve_fonds)
        compte_avances = copro._compte(copro.compte_avances)
        for l in self.coproprietaire_ids:
            ligne(compte_copro, l.solde, l.personne_id)
            ligne(compte_fonds, -l.fonds_travaux, l.personne_id, nom="Fonds de travaux cumulé au %s" % self.date_reprise.strftime("%d/%m/%Y"))
            ligne(compte_avances, -l.avance, l.personne_id, nom="Avance de trésorerie au %s" % self.date_reprise.strftime("%d/%m/%Y"))
        for l in self.autre_ids:
            code = (l.code_compte or "").strip()
            compte = copro._compte(code)
            if (compte.with_company(company).code or "") != code:
                raise UserError("Le compte %s n'existe pas dans le dossier comptable de %s (ligne « %s »)."
                                % (code, copro.name, l.libelle or code))
            ligne(compte, l.debit - l.credit, l.partner_id, nom=l.libelle or libelle)
        if self.facture_ids:
            ligne(copro._compte(COMPTE_ATTENTE), -sum(self.facture_ids.mapped("montant")),
                  nom="Factures fournisseurs reprises")
        return commandes

    def _creer_factures(self, copro):
        Depense = self.env["coproerp.depense"]
        depenses = Depense
        for l in self.facture_ids:
            depense = Depense.create({
                "copropriete_id": copro.id,
                "fournisseur_id": l.fournisseur_id.id,
                "reference_fournisseur": l.reference,
                "date_facture": l.date_facture or self.date_reprise,
                "date_echeance": l.date_echeance or False,
                "reprise_id": self.id,
                "montant_reprise": l.montant,
                "note": l.designation or False,
            })
            depense._valider_reprise()
            depenses |= depense
        return depenses

    def action_annuler(self):
        for reprise in self.filtered(lambda r: r.etat == "validee"):
            company = reprise.copropriete_id._verifier_dossier()
            lignes = reprise.move_id.line_ids.filtered(lambda l: l.account_id.reconcile)
            if any(l.matched_debit_ids or l.matched_credit_ids for l in lignes):
                raise UserError(
                    "Des règlements ont déjà été imputés sur les soldes repris : annulez-les d'abord "
                    "(ou corrigez la reprise par une écriture d'opérations diverses).")
            if reprise.depense_ids.paiement_ids.filtered(lambda p: p.etat == "valide"):
                raise UserError("Des factures reprises ont déjà été payées : annulez d'abord ces paiements.")
            reprise.depense_ids.filtered(lambda d: d.etat == "validee").action_annuler()
            move = reprise.move_id.with_company(company)
            date = max(fields.Date.context_today(reprise), move.date)
            annulation = move._reverse_moves([{"date": date, "ref": "Annulation %s" % move.ref}], cancel=True)
            super(Reprise, reprise).write({"etat": "annulee", "move_annulation_id": annulation.id})
        return True

    def action_voir_factures(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Factures reprises",
            "res_model": "coproerp.depense",
            "view_mode": "list,form",
            "domain": [("reprise_id", "=", self.id)],
        }


class RepriseCoproprietaire(models.Model):
    _name = "coproerp.reprise.coproprietaire"
    _description = "Solde repris d'un copropriétaire"
    _order = "reprise_id, personne_id"

    reprise_id = fields.Many2one("coproerp.reprise", required=True, ondelete="cascade", index=True)
    personne_id = fields.Many2one("res.partner", string="Copropriétaire", required=True)
    solde = fields.Float(
        string="Solde du compte", digits=(16, 2),
        help="Positif : somme due par le copropriétaire. Négatif : somme versée d'avance (compte créditeur).")
    fonds_travaux = fields.Float(string="Fonds de travaux cumulé", digits=(16, 2),
                                 help="Total des cotisations au fonds de travaux attachées à ses lots.")
    avance = fields.Float(string="Avance de trésorerie", digits=(16, 2),
                          help="Fonds de roulement (avance permanente) versé par le copropriétaire.")
    note = fields.Char(string="Observations")

    _personne_unique = models.Constraint(
        "UNIQUE(reprise_id, personne_id)", "Ce copropriétaire figure déjà dans la reprise.")

    @api.constrains("fonds_travaux", "avance")
    def _check_positifs(self):
        for ligne in self:
            if ligne.fonds_travaux < 0 or ligne.avance < 0:
                raise ValidationError("Le fonds de travaux et l'avance ne peuvent pas être négatifs.")


class RepriseFacture(models.Model):
    _name = "coproerp.reprise.facture"
    _description = "Facture fournisseur restant à payer à la date de reprise"
    _order = "reprise_id, date_facture, id"

    reprise_id = fields.Many2one("coproerp.reprise", required=True, ondelete="cascade", index=True)
    fournisseur_id = fields.Many2one("res.partner", string="Fournisseur", required=True)
    reference = fields.Char(string="N° de facture")
    date_facture = fields.Date(string="Date de la facture")
    date_echeance = fields.Date(string="Échéance")
    designation = fields.Char(string="Objet")
    montant = fields.Float(string="Reste à payer", digits=(16, 2), required=True)

    @api.constrains("montant")
    def _check_montant(self):
        for ligne in self:
            if ligne.montant <= 0:
                raise ValidationError("Le reste à payer d'une facture doit être positif.")


class RepriseAutre(models.Model):
    _name = "coproerp.reprise.autre"
    _description = "Autre solde repris"
    _order = "reprise_id, code_compte, id"

    reprise_id = fields.Many2one("coproerp.reprise", required=True, ondelete="cascade", index=True)
    code_compte = fields.Char(string="Compte", required=True, help="Ex. : 102000, 120000, 471000…")
    libelle = fields.Char(string="Libellé")
    partner_id = fields.Many2one("res.partner", string="Tiers")
    debit = fields.Float(string="Débit", digits=(16, 2))
    credit = fields.Float(string="Crédit", digits=(16, 2))

    @api.constrains("debit", "credit")
    def _check_sens(self):
        for ligne in self:
            if ligne.debit < 0 or ligne.credit < 0 or (ligne.debit and ligne.credit):
                raise ValidationError("Indiquez un montant positif, soit au débit, soit au crédit.")


class Depense(models.Model):
    _inherit = "coproerp.depense"

    reprise_id = fields.Many2one("coproerp.reprise", string="Reprise des soldes", readonly=True, index="btree_not_null")
    montant_reprise = fields.Float(string="Reste à payer repris", digits=(16, 2), readonly=True)

    @api.depends("ligne_ids.montant", "montant_reprise", "reprise_id")
    def _compute_montant_total(self):
        super()._compute_montant_total()
        for depense in self.filtered("reprise_id"):
            depense.montant_total = depense.montant_reprise

    def action_valider(self):
        reprises = self.filtered("reprise_id")
        reprises._valider_reprise()
        return super(Depense, self - reprises).action_valider()

    def _valider_reprise(self):
        """Facture antérieure à la reprise : la charge figure déjà dans les comptes du syndic
        précédent ; seule la dette envers le fournisseur est reprise (débit 471 / crédit 401)."""
        for depense in self.filtered(lambda d: d.etat == "brouillon"):
            copro = depense.copropriete_id
            company = copro._verifier_dossier()
            libelle = "Facture reprise %s %s" % (depense.reference_fournisseur or "", depense.fournisseur_id.name or "")
            montant = round(depense.montant_reprise, 2)
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry",
                "journal_id": copro._journal("od").id,
                "date": depense.reprise_id.date_reprise,
                "ref": "%s %s" % (depense.name, libelle),
                "coproerp_depense_id": depense.id,
                "line_ids": [
                    Command.create({"account_id": copro._compte(COMPTE_ATTENTE).id, "name": libelle,
                                    "debit": montant, "credit": 0.0}),
                    Command.create({"account_id": copro._compte(COMPTE_FOURNISSEURS).id,
                                    "partner_id": depense.fournisseur_id.id, "name": libelle,
                                    "debit": 0.0, "credit": montant,
                                    "date_maturity": depense.date_echeance or depense.date_facture}),
                ],
            })
            move.action_post()
            depense.write({"move_id": move.id, "etat": "validee"})
        return True
