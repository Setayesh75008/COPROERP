from odoo import Command, api, fields, models
from odoo.exceptions import UserError

COMPTE_FOURNISSEURS = "401000"


class Depense(models.Model):
    _inherit = "coproerp.depense"

    type_piece = fields.Selection(
        [("facture", "Facture"), ("avoir", "Avoir")], string="Type de pièce", default="facture", required=True,
        help="Un avoir diminue les charges : il est porté au crédit des comptes de charges et vient en déduction "
             "de ce qui est dû au fournisseur.")
    facture_origine_id = fields.Many2one(
        "coproerp.depense", string="Facture d'origine",
        domain="[('copropriete_id', '=', copropriete_id), ('fournisseur_id', '=', fournisseur_id), "
               "('type_piece', '=', 'facture'), ('etat', '=', 'validee')]")
    paiement_groupe_ids = fields.Many2many(
        "coproerp.paiement.groupe", "coproerp_paiement_groupe_depense_rel", "depense_id", "groupe_id",
        string="Paiements groupés", readonly=True)

    def action_valider(self):
        avoirs = self.filtered(lambda d: d.type_piece == "avoir" and d.etat == "brouillon")
        for avoir in avoirs:
            avoir._valider_avoir()
        return super(Depense, self - avoirs).action_valider()

    def _valider_avoir(self):
        self.ensure_one()
        if self.budget_id and hasattr(self.budget_id, "_est_regularise") and self.budget_id._est_regularise():
            raise UserError("Les charges de l'exercice %s sont déjà régularisées : datez l'avoir de l'exercice suivant."
                            % (self.budget_id.exercice or ""))
        copro = self.copropriete_id
        company = copro._verifier_dossier()
        arrondi = company.currency_id.round
        if not self.ligne_ids:
            raise UserError("Ventilez l'avoir : ajoutez au moins une ligne.")
        commandes, total = [], 0.0
        for ligne in self.ligne_ids:
            montant = arrondi(ligne.montant)
            if montant <= 0:
                raise UserError("Saisissez les montants de l'avoir en positif.")
            total += montant
            commandes.append(Command.create({
                "account_id": copro._compte(ligne.nature_id.code).id,
                "partner_id": self.fournisseur_id.id,
                "name": "Avoir – %s" % (ligne.designation or ligne.nature_id.name),
                "credit": montant,
                "coproerp_repartition_id": ligne.repartition_id.id,
                "coproerp_hors_budget": bool(ligne.nature_id.travaux or self.travaux_id),
                "coproerp_travaux_id": self.travaux_id.id or False,
                "coproerp_depense_ligne_id": ligne.id,
            }))
        libelle = "Avoir %s %s" % (self.reference_fournisseur or self.name, self.fournisseur_id.name)
        commandes.append(Command.create({
            "account_id": copro._compte(COMPTE_FOURNISSEURS).id,
            "partner_id": self.fournisseur_id.id,
            "name": libelle,
            "debit": arrondi(total),
        }))
        move = self.env["account.move"].with_company(company).create({
            "move_type": "entry", "journal_id": copro._journal("achats").id, "date": self.date_facture,
            "ref": "%s %s" % (self.name, libelle), "coproerp_depense_id": self.id, "line_ids": commandes,
        })
        move.action_post()
        self.write({"move_id": move.id, "etat": "validee"})
        # Imputation directe sur la facture d'origine encore due
        if self.facture_origine_id and not self.facture_origine_id.est_payee:
            self._lettrer_avec(self.facture_origine_id)
        return True

    def _lettrer_avec(self, autres):
        compte = self.copropriete_id._compte(COMPTE_FOURNISSEURS)
        lignes = (self | autres).move_id.line_ids.filtered(lambda l: l.account_id == compte and not l.reconciled)
        if lignes:
            lignes.reconcile()
        (self | autres)._maj_statut_paiement()

    def action_enregistrer_paiement(self):
        if self.type_piece == "avoir":
            raise UserError("Un avoir ne se paie pas : imputez-le sur une facture (paiement groupé) ou indiquez la "
                            "facture d'origine.")
        return super().action_enregistrer_paiement()
