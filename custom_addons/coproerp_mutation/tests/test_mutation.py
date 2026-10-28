"""Tests des mutations (état daté, vente d'un lot).

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_mutation \
        --test-tags /coproerp_mutation --stop-after-init
"""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_mutation")
class TestMutation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Mutation", "street": "10 rue M", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.lot1 = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        cls.lot2 = env["coproerp.lot"].create({"numero": "2", "designation": "Appartement", "batiment_id": bat.id})
        cls.alice = env["res.partner"].create({"name": "Alice Vendeuse"})
        cls.bob = env["res.partner"].create({"name": "Bob Voisin"})
        cls.claire = env["res.partner"].create({"name": "Claire Acquéreuse"})
        cls.notaire = env["res.partner"].create({"name": "Maître Notaire", "street": "1 place N", "zip": "75001", "city": "Paris"})
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
            "budget_previsionnel": 8000.0, "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 8000.0})],
        })
        cls.copro.action_creer_dossier_comptable()
        cls.copro.recouvrement_cle_frais_id = cls.cle
        cls.company = cls.copro.company_id
        cls.budget.action_generer_appels_budget_tous()
        env["coproerp.appel.charge"].search([("budget_origine_id", "=", cls.budget.id)]).action_comptabiliser()
        env["coproerp.reglement"].create({
            "copropriete_id": cls.copro.id, "personne_id": cls.alice.id,
            "date": date(2026, 2, 1), "montant": 1000.0}).action_valider()
        # Fonds de travaux déjà constitué par Alice : 300 €
        move = env["account.move"].with_company(cls.company).create({
            "move_type": "entry", "journal_id": cls.copro._journal("od").id, "date": date(2026, 1, 2),
            "line_ids": [
                Command.create({"account_id": cls.copro._journal("banque").default_account_id.id,
                                "name": "Fonds", "debit": 300.0}),
                Command.create({"account_id": cls.copro._compte("105000").id, "partner_id": cls.alice.id,
                                "name": "Fonds de travaux", "credit": 300.0}),
            ],
        })
        move.action_post()

    def _mutation(self, **vals):
        return self.env["coproerp.mutation"].create({
            "copropriete_id": self.copro.id, "lot_ids": [Command.set(self.lot1.ids)],
            "vendeur_id": self.alice.id, "notaire_id": self.notaire.id,
            "date_etat": date(2026, 5, 15), **vals,
        })

    def _solde(self, code, partner):
        dom = [("company_id", "=", self.company.id), ("account_id", "=", self.copro._compte(code).id),
               ("parent_state", "=", "posted"), ("partner_id", "=", partner.id)]
        return round(sum(self.env["account.move.line"].search(dom).mapped("balance")), 2)

    # ---------------------------------------------------------------
    def test_calcul_etat_date(self):
        mutation = self._mutation()
        self.assertAlmostEqual(mutation.honoraires, 380.0)
        d = mutation.calculer()
        # Appels de janvier et avril : 2 x 1 200 = 2 400, moins 1 000 réglés
        self.assertAlmostEqual(d["partie1"]["budget"], 1400.0)
        self.assertAlmostEqual(d["partie1"]["anterieur"], 0.0)
        # Quote-part annuelle 4 800, dont 2 400 encore à appeler après le 15 mai
        self.assertAlmostEqual(d["budget_annuel"], 4800.0)
        self.assertAlmostEqual(d["partie3"]["budget"], 2400.0)
        self.assertAlmostEqual(d["fonds_lot"], 300.0)

    def test_emission_fige_et_impute_les_honoraires(self):
        mutation = self._mutation()
        mutation.action_emettre_etat_date()
        self.assertEqual(mutation.etat, "emis")
        self.assertAlmostEqual(mutation.donnees()["partie1"]["total"], 1780.0)
        credit = mutation.move_honoraires_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.account_id.with_company(self.company).code, "714000")
        self.assertEqual(credit.coproerp_repartition_id, self.cle)
        with self.assertRaises(UserError):
            mutation.honoraires = 100.0
        # Le certificat de l'article 20 est refusé : la vendeuse doit encore de l'argent
        with self.assertRaises(UserError):
            mutation.action_imprimer_certificat()
        mutation.action_remettre_brouillon()
        self.assertEqual(mutation.etat, "brouillon")
        self.assertAlmostEqual(mutation.calculer()["partie1"]["total"], 1400.0)

    def test_plafond_des_honoraires(self):
        with self.assertRaises(ValidationError):
            self._mutation(honoraires=450.0)

    def test_realisation_de_la_vente(self):
        mutation = self._mutation(acquereur_id=self.claire.id, date_acte=date(2026, 6, 1))
        mutation.action_realiser_vente()
        self.assertEqual(mutation.etat, "vendu")
        # Changement de propriétaire du lot
        self.assertEqual(self.lot1._destinataire_appels(date(2026, 6, 2))[0], self.claire)
        self.assertEqual(self.lot1._destinataire_appels(date(2026, 5, 20))[0], self.alice)
        # Le fonds de travaux attaché au lot suit le lot
        self.assertAlmostEqual(self._solde("105000", self.alice), 0.0)
        self.assertAlmostEqual(self._solde("105000", self.claire), -300.0)
        with self.assertRaises(UserError):
            mutation.action_annuler()

    def test_documents_pdf(self):
        mutation = self._mutation()
        Report = self.env["ir.actions.report"]
        html = Report._render_qweb_html("coproerp_mutation.report_etat_date", mutation.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("ÉTAT DATÉ", "PROJET", "SOMMES DUES PAR LE VENDEUR", "NOUVEAU COPROPRIÉTAIRE",
                      "Maître Notaire", "1 400,00"):
            self.assertIn(texte, html)
        html = Report._render_qweb_html("coproerp_mutation.report_pre_etat_date", mutation.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("PRÉ-ÉTAT DATÉ", html)
        self.assertIn("4 800,00", html)
