from datetime import date

from odoo import Command
from odoo.tests.common import TransactionCase


class CoproGestionCase(TransactionCase):
    """Copropriété de deux lots, exercice 2026, appels comptabilisés."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.syndic = env["res.partner"].create({"name": "Cabinet Syndic Courant", "is_company": True})
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Gestion Courante", "street": "8 rue G", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185", "syndic_id": cls.syndic.id,
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.lot1 = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        cls.lot2 = env["coproerp.lot"].create({"numero": "2", "designation": "Appartement", "batiment_id": bat.id})
        cls.alice = env["res.partner"].create({"name": "Alice Martineau"})
        cls.bob = env["res.partner"].create({"name": "Bob Durandal"})
        env["coproerp.droit"].create({"personne_id": cls.alice.id, "lot_id": cls.lot1.id, "type_droit": "proprietaire"})
        env["coproerp.droit"].create({"personne_id": cls.bob.id, "lot_id": cls.lot2.id, "type_droit": "proprietaire"})
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": cls.lot1.id, "tantiemes": 600})
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": cls.lot2.id, "tantiemes": 400})
        cls.budget = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": 2026,
            "date_debut": date(2026, 1, 1), "date_fin": date(2026, 12, 31),
            "budget_previsionnel": 8000.0,
            "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 8000.0})],
        })
        cls.copro.action_creer_dossier_comptable()
        cls.company = cls.copro.company_id
        cls.budget.action_generer_appels_budget_tous()
        env["coproerp.appel.charge"].search([("budget_origine_id", "=", cls.budget.id)]).action_comptabiliser()
        cls.fournisseur = env["res.partner"].create({"name": "Plomberie Lavoisier SARL"})
        Nature = env["coproerp.nature.depense"]
        cls.n_entretien = Nature.search([("code", "=", "615000")])
        cls.n_assurance = Nature.search([("code", "=", "616000")])

    # ---------------------------------------------------------------
    def _solde(self, code, partner=None):
        dom = [("company_id", "=", self.company.id), ("account_id", "=", self.copro._compte(code).id),
               ("parent_state", "=", "posted")]
        if partner:
            dom.append(("partner_id", "=", partner.id))
        return round(sum(self.env["account.move.line"].search(dom).mapped("balance")), 2)

    def _reglement(self, personne, jour, montant):
        reglement = self.env["coproerp.reglement"].create({
            "copropriete_id": self.copro.id, "personne_id": personne.id, "date": jour, "montant": montant})
        reglement.action_valider()
        return reglement

    def _piece(self, montant, ref, type_piece="facture", jour=date(2026, 3, 10), **vals):
        return self.env["coproerp.depense"].create({
            "copropriete_id": self.copro.id, "fournisseur_id": self.fournisseur.id,
            "reference_fournisseur": ref, "date_facture": jour, "type_piece": type_piece,
            "ligne_ids": [Command.create({"nature_id": self.n_entretien.id, "repartition_id": self.cle.id,
                                          "montant": montant})],
            **vals,
        })
