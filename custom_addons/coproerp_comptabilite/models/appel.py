from odoo import Command, api, fields, models
from odoo.exceptions import UserError

CHAMPS_VERROUILLES_APPEL = {
    "personne_id", "copropriete_id", "type_appel", "date_echeance", "groupe_ids",
    "budget_id", "travaux_id",
}
CHAMPS_VERROUILLES_GROUPE = {"lot_id", "poste_ids", "appel_id"}
CHAMPS_VERROUILLES_POSTE = {"total_a_repartir", "repartition_id", "type_poste", "groupe_id"}


class AppelCharge(models.Model):
    _inherit = "coproerp.appel.charge"

    move_id = fields.Many2one("account.move", string="Écriture comptable", readonly=True, copy=False)
    move_annulation_id = fields.Many2one("account.move", string="Écriture d'annulation", readonly=True, copy=False)
    etat_comptable = fields.Selection(
        [("projet", "Projet"), ("comptabilise", "Comptabilisé"), ("annule", "Annulé")],
        string="État comptable",
        default="projet",
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    montant_restant = fields.Float(
        string="Reste à payer",
        compute="_compute_montant_restant",
        digits=(16, 2),
    )

    @api.depends(
        "move_id.line_ids.amount_residual",
        "move_id.line_ids.reconciled",
        "total_appel",
    )
    def _compute_montant_restant(self):
        for appel in self:
            lignes = appel.move_id.sudo().line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable" and l.debit
            )
            appel.montant_restant = sum(lignes.mapped("amount_residual")) if appel.move_id else appel.total_appel

    # ------------------------------------------------------------------
    # Comptabilisation
    # ------------------------------------------------------------------
    def _libelle_comptable(self):
        self.ensure_one()
        titre = self.titre_section(self).capitalize()
        return "Appel %s — %s" % (self.libelle_echeance or self.reference or "", titre)

    def action_comptabiliser(self):
        arrondi = None
        for appel in self.filtered(lambda a: a.etat_comptable == "projet"):
            company = appel.copropriete_id._verifier_dossier()
            appel = appel.with_company(company)
            copro = appel.copropriete_id
            arrondi = company.currency_id.round
            if appel.total_appel <= 0:
                raise UserError("L'appel %s a un montant nul : rien à comptabiliser." % appel.reference)
            tiers, contrepartie = copro._comptes_par_type(appel.type_appel)
            libelle = appel._libelle_comptable()

            # Une ligne de crédit par poste de dépense (libellé de l'avis)
            credits = {}
            for poste in appel.groupe_ids.poste_ids:
                credits[poste.designation] = credits.get(poste.designation, 0.0) + poste.montant_appel
            commandes = []
            total = 0.0
            for designation, montant in credits.items():
                montant = arrondi(montant)
                if not montant:
                    continue
                total += montant
                commandes.append(Command.create({
                    "account_id": contrepartie.id,
                    "partner_id": appel.personne_id.id,
                    "name": "%s — %s" % (appel.reference or "", designation),
                    "debit": 0.0 if montant > 0 else -montant,
                    "credit": montant if montant > 0 else 0.0,
                }))
            total = arrondi(total)
            commandes.insert(0, Command.create({
                "account_id": tiers.id,
                "partner_id": appel.personne_id.id,
                "name": libelle,
                "debit": total,
                "credit": 0.0,
                "date_maturity": appel.date_echeance,
            }))
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry",
                "journal_id": copro._journal("appels").id,
                # Date d'exigibilité, comme sur les relevés de compte
                "date": appel.date_echeance,
                "ref": "%s %s" % (appel.reference or "", appel.personne_id.name or ""),
                "coproerp_appel_id": appel.id,
                "line_ids": commandes,
            })
            move.action_post()
            appel.write({"move_id": move.id, "etat_comptable": "comptabilise"})
            appel._lettrer_avec_avoirs()
        return True

    def _lettrer_avec_avoirs(self):
        """Impute sur l'appel les sommes déjà versées d'avance (trop-perçus)."""
        for appel in self:
            if not appel.move_id:
                continue
            appel = appel.with_company(appel.sudo().move_id.company_id)
            debit = appel.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable" and l.debit
            )
            if not debit:
                continue
            credits = self.env["account.move.line"].search([
                ("company_id", "=", appel.move_id.company_id.id),
                ("account_id", "=", debit.account_id.id),
                ("partner_id", "=", debit.partner_id.id),
                ("parent_state", "=", "posted"),
                ("reconciled", "=", False),
                ("amount_residual", "<", 0),
            ], order="date, id")
            if credits:
                (debit | credits).reconcile()

    def action_annuler_comptabilisation(self):
        """Annule l'écriture par contre-passation (l'écriture d'origine reste visible)."""
        for appel in self.filtered(lambda a: a.etat_comptable == "comptabilise"):
            appel = appel.with_company(appel.copropriete_id._verifier_dossier())
            date = fields.Date.context_today(self)
            if date < appel.move_id.date:
                date = appel.move_id.date
            annulation = appel.move_id._reverse_moves(
                [{"date": date, "ref": "Annulation %s" % (appel.move_id.ref or "")}], cancel=True
            )
            appel.write({"etat_comptable": "annule", "move_annulation_id": annulation.id})
        return True

    # ------------------------------------------------------------------
    # Verrouillage après comptabilisation
    # ------------------------------------------------------------------
    def write(self, vals):
        if CHAMPS_VERROUILLES_APPEL & set(vals) and self.filtered("move_id"):
            raise UserError(
                "Cet appel est comptabilisé : il ne peut plus être modifié. "
                "Annulez-le (contre-passation) puis créez un nouvel appel."
            )
        return super().write(vals)

    def unlink(self):
        if self.filtered("move_id"):
            raise UserError("Un appel comptabilisé ne peut pas être supprimé.")
        return super().unlink()

    # ------------------------------------------------------------------
    # Avis d'appel : relevé de compte
    # ------------------------------------------------------------------
    def avis_regroupes(self):
        avis_liste = super().avis_regroupes()
        for avis in avis_liste:
            appels = avis["appels"]
            copro = avis["copro"]
            if not copro.company_id:
                continue
            avis["projet"] = any(a.etat_comptable != "comptabilise" for a in appels)
            personne = avis["personne"]
            # Précédent relevé : celui de l'avis précédent adressé à ce
            # copropriétaire, arrêté à sa date d'échéance (« solde au »).
            precedent = self.search([
                ("copropriete_id", "=", copro.id),
                ("personne_id", "=", personne.id),
                ("date_echeance", "<", avis["date_echeance"]),
                ("id", "not in", appels.ids),
                ("etat_comptable", "=", "comptabilise"),
            ], order="date_echeance desc", limit=1)
            date_precedent = precedent.date_echeance if precedent else False
            # Le relevé est arrêté à la date d'échéance, ou à la date du jour si
            # l'avis est imprimé plus tard : les règlements déjà reçus doivent
            # y figurer, sinon on réclamerait des sommes déjà payées.
            date_fin = max(avis["date_echeance"], fields.Date.context_today(self))
            releve = copro.sudo().releve_compte(personne, date_precedent, date_fin)
            # Appels de cet avis pas encore comptabilisés : présentés pour mémoire
            for appel in appels.filtered(lambda a: a.etat_comptable == "projet"):
                releve["mouvements"].append({
                    "date": appel.date_echeance,
                    "libelle": appel._libelle_comptable() + " (projet)",
                    "debit": appel.total_appel,
                    "credit": 0.0,
                })
                releve["solde"] = round(releve["solde"] + appel.total_appel, 2)
            # Ordre chronologique (l'appel en projet peut être antérieur à un règlement)
            releve["mouvements"].sort(key=lambda m: m["date"])
            avis["releve"] = releve
            avis["a_regler"] = max(releve["solde"], 0.0)
            avis["fonds"] = copro.sudo().fonds_du_coproprietaire(personne)
        return avis_liste


class AppelChargeGroupe(models.Model):
    _inherit = "coproerp.appel.charge.groupe"

    def write(self, vals):
        if CHAMPS_VERROUILLES_GROUPE & set(vals) and self.appel_id.filtered("move_id"):
            raise UserError("Cet appel est comptabilisé : le détail par lot ne peut plus être modifié.")
        return super().write(vals)

    def unlink(self):
        if self.appel_id.filtered("move_id"):
            raise UserError("Cet appel est comptabilisé : le détail par lot ne peut plus être supprimé.")
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        groupes = super().create(vals_list)
        if groupes.appel_id.filtered("move_id"):
            raise UserError("Cet appel est comptabilisé : on ne peut plus y ajouter de lot.")
        return groupes


class AppelChargePoste(models.Model):
    _inherit = "coproerp.appel.charge.poste"

    def write(self, vals):
        if CHAMPS_VERROUILLES_POSTE & set(vals) and self.appel_id.filtered("move_id"):
            raise UserError("Cet appel est comptabilisé : ses montants ne peuvent plus être modifiés.")
        return super().write(vals)

    def unlink(self):
        if self.appel_id.filtered("move_id"):
            raise UserError("Cet appel est comptabilisé : ses postes ne peuvent plus être supprimés.")
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        postes = super().create(vals_list)
        if postes.appel_id.filtered("move_id"):
            raise UserError("Cet appel est comptabilisé : on ne peut plus y ajouter de poste.")
        return postes
