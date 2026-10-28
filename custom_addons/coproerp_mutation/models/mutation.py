import json
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .copropriete import PLAFOND_ETAT_DATE

COMPTE_FRAIS = "714000"
TYPES_TITULAIRES = ("proprietaire", "indivisaire", "usufruitier", "nu_proprietaire")


def _r(valeur):
    return round(valeur or 0.0, 2)


class Mutation(models.Model):
    """Dossier de vente d'un ou plusieurs lots : pré-état daté, état daté, transfert."""

    _name = "coproerp.mutation"
    _description = "Mutation d'un lot (vente)"
    _inherit = ["mail.thread"]
    _order = "date_demande desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="restrict", tracking=True)
    lot_ids = fields.Many2many(
        "coproerp.lot", "coproerp_mutation_lot_rel", "mutation_id", "lot_id", string="Lots vendus",
        domain="[('copropriete_id', '=', copropriete_id)]", tracking=True)
    vendeur_id = fields.Many2one("res.partner", string="Vendeur", required=True, tracking=True)
    acquereur_id = fields.Many2one("res.partner", string="Acquéreur", tracking=True)
    notaire_id = fields.Many2one("res.partner", string="Notaire", tracking=True)
    reference_notaire = fields.Char(string="Référence du notaire")
    date_demande = fields.Date(string="Demande reçue le", default=fields.Date.context_today, required=True)
    date_etat = fields.Date(
        string="État arrêté au", default=fields.Date.context_today, required=True,
        help="Date à laquelle les sommes de l'état daté sont arrêtées.")
    date_acte = fields.Date(string="Date de la vente (acte authentique)", tracking=True)
    honoraires = fields.Float(
        string="Honoraires d'état daté", digits=(16, 2),
        help="Imputés au seul vendeur (art. 10-1 de la loi). Plafond : 380 € TTC.")
    provisions_19_2 = fields.Float(
        string="Provisions rendues exigibles par anticipation (art. 19-2)", digits=(16, 2),
        help="Provisions des périodes postérieures rendues exigibles après une mise en demeure restée "
             "sans effet (à reverser au vendeur si elles ont été payées).")
    procedures = fields.Text(
        string="Procédures en cours",
        help="Procédures judiciaires en cours concernant le syndicat ou le lot, à porter à la connaissance de "
             "l'acquéreur.")
    observations = fields.Text(string="Observations")
    transferer_avance = fields.Boolean(
        string="Transférer l'avance de trésorerie à l'acquéreur", default=True,
        help="L'avance (fonds de roulement) du vendeur est reprise par l'acquéreur ; son remboursement au "
             "vendeur est réglé entre les parties chez le notaire (état daté, parties II et III).")
    etat = fields.Selection(
        [("brouillon", "En préparation"), ("emis", "État daté émis"), ("vendu", "Vente réalisée"),
         ("annule", "Annulé")],
        string="État", default="brouillon", required=True, readonly=True, copy=False, tracking=True)
    donnees_figees = fields.Text(readonly=True, copy=False)
    move_honoraires_id = fields.Many2one("account.move", string="Écriture des honoraires", readonly=True, copy=False)
    move_transfert_id = fields.Many2one("account.move", string="Écriture de transfert", readonly=True, copy=False)
    solde_vendeur = fields.Float(string="Solde actuel du vendeur", compute="_compute_solde_vendeur", digits=(16, 2))

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        Copro = self.env["coproerp.copropriete"]
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.mutation") or "/"
            if "honoraires" not in vals and vals.get("copropriete_id"):
                vals["honoraires"] = Copro.browse(vals["copropriete_id"]).mutation_honoraires_etat_date
        return super().create(vals_list)

    @api.constrains("honoraires")
    def _check_honoraires(self):
        for mutation in self:
            if mutation.honoraires < 0 or mutation.honoraires > PLAFOND_ETAT_DATE + 0.001:
                raise ValidationError("Les honoraires d'état daté sont compris entre 0 et 380 € TTC.")

    @api.constrains("date_etat", "date_acte")
    def _check_dates(self):
        aujourdhui = fields.Date.context_today(self)
        for mutation in self:
            if mutation.date_etat and mutation.date_etat > aujourdhui:
                raise ValidationError("L'état daté ne peut pas être arrêté à une date future.")

    def write(self, vals):
        figes = {"copropriete_id", "lot_ids", "vendeur_id", "date_etat", "honoraires", "provisions_19_2"}
        if figes & set(vals) and self.filtered(lambda m: m.etat in ("emis", "vendu")):
            raise UserError("L'état daté est émis : remettez le dossier en préparation pour le modifier.")
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda m: m.etat != "brouillon"):
            raise UserError("Seul un dossier en préparation peut être supprimé.")
        return super().unlink()

    def _compute_solde_vendeur(self):
        for mutation in self:
            solde = 0.0
            if mutation.copropriete_id.company_id and mutation.vendeur_id:
                solde = mutation.copropriete_id.situation_debiteur(
                    mutation.vendeur_id, fields.Date.context_today(mutation))["solde"]
            mutation.solde_vendeur = solde

    @api.onchange("lot_ids")
    def _onchange_lot_ids(self):
        if self.lot_ids and not self.vendeur_id:
            partner, _erreur = self.lot_ids[0]._destinataire_appels(self.date_etat)
            self.vendeur_id = partner

    # ------------------------------------------------------------------
    # Calculs
    # ------------------------------------------------------------------
    def _soldes_comptes(self, date, date_min_exclue=None):
        """Soldes du vendeur par compte copropriétaire (débit positif)."""
        copro = self.copropriete_id.sudo()
        company = copro._verifier_dossier()
        lignes = copro._lignes_coproprietaires([self.vendeur_id.id], date_max=date, date_min_exclue=date_min_exclue)
        soldes = {}
        for ligne in lignes:
            code = ligne.account_id.with_company(company).code
            soldes[code] = soldes.get(code, 0.0) + ligne.balance
        return soldes

    def _solde_compte(self, code, signe=-1, date=None):
        """Solde (crédit positif par défaut) d'un compte pour le vendeur, jusqu'à la date de l'état."""
        copro = self.copropriete_id.sudo()
        company = copro._verifier_dossier()
        try:
            compte = copro._compte(code)
        except UserError:
            return 0.0
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id), ("account_id", "=", compte.id),
            ("partner_id", "=", self.vendeur_id.id), ("parent_state", "=", "posted"),
            ("date", "<=", date or self.date_etat),
        ])
        return signe * sum(lignes.mapped("balance"))

    @staticmethod
    def _part(cle, lots):
        """Part (fraction) des lots dans une clé de répartition."""
        if not cle or not cle.total_tantiemes:
            return 0.0
        parts = sum(l.tantiemes for l in cle.line_ids if l.lot_id in lots)
        return parts / cle.total_tantiemes

    def _lots_du_vendeur(self):
        """Tous les lots dont le vendeur est titulaire à la date de l'état."""
        lots = self.env["coproerp.lot"].search([("copropriete_id", "=", self.copropriete_id.id)])
        return lots.filtered(lambda l: self.vendeur_id in l._titulaires_appels(self.date_etat)
                             or l.mandataire_commun_id == self.vendeur_id) | self.lot_ids

    def _budget_en_cours(self, date=None):
        date = date or self.date_etat
        return self.env["coproerp.budget.annuel"].search([
            ("copropriete_id", "=", self.copropriete_id.id),
            ("date_debut", "<=", date), ("date_fin", ">=", date),
        ], order="date_debut desc", limit=1)

    def _ratio(self, date=None):
        """Part des lots vendus dans l'ensemble des lots du vendeur (clé du fonds de travaux)."""
        budget = self._budget_en_cours(date)
        cle_fonds = budget.repartition_fonds_travaux_id if budget else False
        if not cle_fonds:
            return 1.0
        total_vendeur = self._part(cle_fonds, self._lots_du_vendeur())
        return self._part(cle_fonds, self.lot_ids) / total_vendeur if total_vendeur else 1.0

    def _provisions(self, budget, type_appel, cle_lignes):
        """Quote-part annuelle des lots vendus et part déjà exigible à la date de l'état."""
        annuel = sum(montant * self._part(cle, self.lot_ids) for cle, montant in cle_lignes)
        postes = self.env["coproerp.appel.charge.poste"].sudo().search([
            ("lot_id", "in", self.lot_ids.ids),
            ("appel_id.type_appel", "=", type_appel),
            ("appel_id.date_echeance", "<=", self.date_etat),
            "|", ("appel_id.budget_origine_id", "=", budget.id), ("appel_id.budget_id", "=", budget.id),
        ])
        exigible = sum(postes.mapped("montant_appel"))
        return _r(annuel), _r(max(annuel - exigible, 0.0))

    def calculer(self):
        """Toutes les données de l'état daté et du pré-état daté (non figées)."""
        self.ensure_one()
        copro = self.copropriete_id.sudo()
        copro._verifier_dossier()
        if not self.lot_ids:
            raise UserError("Indiquez le ou les lots vendus.")
        date = self.date_etat
        budget = self._budget_en_cours()
        soldes = self._soldes_comptes(date)
        code_budget, code_travaux = copro.compte_copro_budget, copro.compte_copro_travaux
        code_avances, code_fonds = copro.compte_copro_avances, copro.compte_copro_fonds
        # Partie I : sommes dues par le vendeur
        anterieur = 0.0
        if budget:
            veille = budget.date_debut - timedelta(days=1)
            anterieur = max(self._soldes_comptes(veille).get(code_budget, 0.0), 0.0)
        budget_du = max(soldes.get(code_budget, 0.0), 0.0)
        partie1 = {
            "budget": _r(max(budget_du - anterieur, 0.0)),
            "travaux": _r(max(soldes.get(code_travaux, 0.0), 0.0)),
            "anterieur": _r(min(anterieur, budget_du)),
            "avances": _r(max(soldes.get(code_avances, 0.0), 0.0)),
            "fonds": _r(max(soldes.get(code_fonds, 0.0), 0.0)),
        }
        partie1["total"] = _r(sum(partie1.values()))
        # Partie II : sommes dues au vendeur
        cle_fonds = budget.repartition_fonds_travaux_id if budget else False
        ratio = self._ratio()
        avance = _r(max(self._solde_compte(copro.compte_avances), 0.0) * ratio)
        crediteur = _r(sum(-s for s in soldes.values() if s < 0))
        partie2 = {"avances": avance, "provisions_19_2": _r(self.provisions_19_2), "crediteur": crediteur}
        partie2["total"] = _r(sum(partie2.values()))
        # Partie III : sommes à la charge de l'acquéreur
        budget_annuel = budget_restant = fonds_annuel = fonds_restant = 0.0
        if budget:
            budget_annuel, budget_restant = self._provisions(
                budget, "budget_courant", [(l.repartition_id, l.montant_annuel) for l in budget.ligne_ids])
            if cle_fonds and budget.cotisation_annuelle_fonds:
                fonds_annuel, fonds_restant = self._provisions(
                    budget, "fonds_travaux", [(cle_fonds, budget.cotisation_annuelle_fonds)])
        travaux = []
        echeances = self.env["coproerp.travaux.echeance"].sudo().search([
            ("copropriete_id", "=", copro.id), ("date_echeance", ">", date)], order="date_echeance")
        for echeance in echeances:
            part = self._part(echeance.financement_id.repartition_id, self.lot_ids)
            montant = _r((echeance.montant + echeance.montant_honoraires) * part)
            if montant:
                travaux.append({"libelle": "%s – %s" % (echeance.travaux_id.display_name, echeance.name or ""),
                                "date": echeance.date_echeance, "montant": montant})
        partie3 = {
            "avances": avance,
            "budget": budget_restant,
            "fonds": fonds_restant,
            "travaux": _r(sum(t["montant"] for t in travaux)),
        }
        partie3["total"] = _r(sum(partie3.values()))
        # Informations complémentaires
        fonds_lot = _r(max(self._solde_compte(copro.compte_reserve_fonds)
                           + self._solde_compte(copro.compte_produit_fonds), 0.0) * ratio)
        return {
            "partie1": partie1, "partie2": partie2, "partie3": partie3, "travaux": travaux,
            "fonds_lot": fonds_lot, "ratio": ratio,
            "budget_annuel": budget_annuel, "fonds_annuel": fonds_annuel,
            "budget": {"exercice": budget.exercice, "debut": str(budget.date_debut), "fin": str(budget.date_fin),
                       "montant": _r(sum(budget.ligne_ids.mapped("montant_annuel")) or budget.budget_previsionnel)}
            if budget else None,
            "charges_passees": self._charges_passees(),
            "solde": _r(sum(soldes.values())),
        }

    def _charges_passees(self):
        """Charges courantes réelles des lots vendus sur les deux derniers exercices régularisés."""
        reguls = self.env["coproerp.regularisation"].sudo().search([
            ("copropriete_id", "=", self.copropriete_id.id), ("etat", "=", "comptabilisee"),
        ], order="date_fin desc", limit=2)
        resultat = []
        for regul in reguls:
            lignes = regul.ligne_ids.filtered(lambda l: l.lot_id in self.lot_ids)
            resultat.append({"exercice": regul.budget_id.exercice, "debut": str(regul.date_debut),
                             "fin": str(regul.date_fin), "charges": _r(sum(lignes.mapped("quote_part"))),
                             "provisions": _r(sum(lignes.mapped("provisions")))})
        return resultat

    def donnees(self):
        """Données figées à l'émission de l'état daté, sinon calculées à la volée."""
        self.ensure_one()
        if self.donnees_figees:
            return json.loads(self.donnees_figees)
        return json.loads(json.dumps(self.calculer(), default=str))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_emettre_etat_date(self):
        for mutation in self.filtered(lambda m: m.etat == "brouillon"):
            copro = mutation.copropriete_id
            company = copro._verifier_dossier()
            vals = {}
            if mutation.honoraires and not mutation.move_honoraires_id:
                if not copro.recouvrement_cle_frais_id:
                    raise UserError(
                        "Indiquez la « clé des honoraires de recouvrement » (onglet Recouvrement de la copropriété) : "
                        "les honoraires d'état daté imputés au vendeur viennent en déduction de cette clé.")
                libelle = "Honoraires d'état daté %s (art. 10-1)" % mutation.name
                move = self.env["account.move"].with_company(company).create({
                    "move_type": "entry",
                    "journal_id": copro._journal("od").id,
                    "date": mutation.date_etat,
                    "ref": "%s %s" % (mutation.name, mutation.vendeur_id.name or ""),
                    "line_ids": [
                        Command.create({"account_id": copro._compte(copro.compte_copro_budget).id,
                                        "partner_id": mutation.vendeur_id.id, "name": "Honoraires d'état daté",
                                        "debit": _r(mutation.honoraires)}),
                        Command.create({"account_id": copro._compte(COMPTE_FRAIS).id,
                                        "partner_id": mutation.vendeur_id.id, "name": libelle,
                                        "credit": _r(mutation.honoraires),
                                        "coproerp_repartition_id": copro.recouvrement_cle_frais_id.id}),
                    ],
                })
                move.action_post()
                vals["move_honoraires_id"] = move.id
            donnees = mutation.calculer()
            vals.update({"etat": "emis", "donnees_figees": json.dumps(donnees, default=str)})
            super(Mutation, mutation).write(vals)
            mutation.message_post(body="État daté émis : %.2f € dus par le vendeur." % donnees["partie1"]["total"])
        return True

    def action_remettre_brouillon(self):
        for mutation in self.filtered(lambda m: m.etat == "emis"):
            vals = {"etat": "brouillon", "donnees_figees": False}
            if mutation.move_honoraires_id:
                company = mutation.copropriete_id._verifier_dossier()
                move = mutation.move_honoraires_id.with_company(company)
                # Contre-passation à la même date : l'état daté recalculé à cette date
                # ne comprend plus les honoraires annulés.
                date = move.date
                move._reverse_moves([{"date": date, "ref": "Annulation %s" % move.ref}], cancel=True)
                vals["move_honoraires_id"] = False
            super(Mutation, mutation).write(vals)
        return True

    def action_annuler(self):
        self.filtered(lambda m: m.etat == "emis").action_remettre_brouillon()
        for mutation in self.filtered(lambda m: m.etat == "vendu"):
            raise UserError("La vente est réalisée : le dossier ne peut plus être annulé.")
        super(Mutation, self.filtered(lambda m: m.etat == "brouillon")).write({"etat": "annule"})
        return True

    def action_realiser_vente(self):
        """Change le propriétaire des lots et transfère le fonds de travaux (et l'avance)."""
        for mutation in self:
            if mutation.etat not in ("brouillon", "emis"):
                raise UserError("La vente est déjà réalisée ou le dossier est annulé.")
            if not mutation.acquereur_id or not mutation.date_acte:
                raise UserError("Indiquez l'acquéreur et la date de la vente.")
            if mutation.date_acte > fields.Date.context_today(mutation):
                raise UserError("La vente ne peut être enregistrée qu'à compter de la date de l'acte.")
            if mutation.acquereur_id == mutation.vendeur_id:
                raise UserError("L'acquéreur doit être différent du vendeur.")
            copro = mutation.copropriete_id
            company = copro._verifier_dossier()
            # 1. Transfert du fonds de travaux attaché aux lots (et de l'avance), calculé avant le
            #    changement de propriétaire
            ratio = mutation._ratio(mutation.date_acte)
            commandes = []

            def transferer(code, libelle):
                montant = _r(mutation._solde_compte(code, date=mutation.date_acte) * ratio)
                if montant > 0:
                    compte = copro._compte(code)
                    commandes.extend([
                        Command.create({"account_id": compte.id, "partner_id": mutation.vendeur_id.id,
                                        "name": libelle, "debit": montant}),
                        Command.create({"account_id": compte.id, "partner_id": mutation.acquereur_id.id,
                                        "name": libelle, "credit": montant}),
                    ])

            transferer(copro.compte_reserve_fonds, "Fonds de travaux attaché au(x) lot(s) vendu(s)")
            transferer(copro.compte_produit_fonds, "Cotisations au fonds de travaux de l'exercice (lots vendus)")
            if mutation.transferer_avance:
                transferer(copro.compte_avances, "Avance de trésorerie reprise par l'acquéreur")
            # 2. Changement de propriétaire
            Droit = self.env["coproerp.droit"]
            veille = mutation.date_acte - timedelta(days=1)
            for lot in mutation.lot_ids:
                droits = lot.droit_ids.filtered(
                    lambda d: d.active and d.personne_id == mutation.vendeur_id and d.type_droit in TYPES_TITULAIRES
                    and (not d.date_fin or d.date_fin >= mutation.date_acte))
                droits.write({"date_fin": veille})
                Droit.create({"personne_id": mutation.acquereur_id.id, "lot_id": lot.id,
                              "type_droit": "proprietaire", "date_debut": mutation.date_acte})
                if lot.mandataire_commun_id == mutation.vendeur_id:
                    lot.mandataire_commun_id = False
            vals = {"etat": "vendu"}
            if commandes:
                move = self.env["account.move"].with_company(company).create({
                    "move_type": "entry",
                    "journal_id": copro._journal("od").id,
                    "date": mutation.date_acte,
                    "ref": "%s Vente %s → %s" % (mutation.name, mutation.vendeur_id.name, mutation.acquereur_id.name),
                    "line_ids": commandes,
                })
                move.action_post()
                vals["move_transfert_id"] = move.id
            super(Mutation, mutation).write(vals)
            mutation.message_post(body="Vente réalisée le %s : %s devient propriétaire." % (
                mutation.date_acte.strftime("%d/%m/%Y"), mutation.acquereur_id.name))
        return True

    def _rapport(self, xmlid):
        return self.env.ref("coproerp_mutation.%s" % xmlid).report_action(self)

    def action_imprimer_etat_date(self):
        return self._rapport("action_report_etat_date")

    def action_imprimer_pre_etat_date(self):
        return self._rapport("action_report_pre_etat_date")

    def action_imprimer_certificat(self):
        self.ensure_one()
        if self.solde_vendeur > 0.005:
            raise UserError("Le vendeur reste redevable de %.2f € : le certificat de l'article 20 ne peut pas être "
                            "délivré." % self.solde_vendeur)
        return self._rapport("action_report_certificat_art20")

    # -- aides pour les modèles d'impression --------------------------------
    def fmt(self, valeur):
        return "{:,.2f}".format(valeur or 0.0).replace(",", " ").replace(".", ",")

    def date_fr(self, valeur):
        if not valeur:
            return ""
        d = fields.Date.to_date(valeur)
        return d.strftime("%d/%m/%Y")

    def lots_texte(self):
        self.ensure_one()
        return ", ".join("lot n° %s%s" % (l.numero, (" (%s)" % l.designation) if l.designation else "")
                         for l in self.lot_ids)

    def tantiemes_lots(self):
        """[(clé, tantièmes des lots, total)] pour les clés de la copropriété."""
        self.ensure_one()
        cles = self.env["coproerp.repartition"].search([("copropriete_id", "=", self.copropriete_id.id)])
        resultat = []
        for cle in cles:
            parts = sum(l.tantiemes for l in cle.line_ids if l.lot_id in self.lot_ids)
            if parts:
                resultat.append((cle.name, parts, cle.total_tantiemes))
        return resultat
