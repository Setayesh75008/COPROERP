"""Tests de la régularisation annuelle des charges.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_regularisation \
        --test-tags /coproerp_regularisation --stop-after-init
"""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.regularisation import repartir


@tagged("post_install", "-at_install", "coproerp_regularisation")
class TestRegularisation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Régul", "street": "4 rue R", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.lot1 = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        cls.lot2 = env["coproerp.lot"].create({"numero": "2", "designation": "Appartement", "batiment_id": bat.id})
        cls.alice = env["res.partner"].create({"name": "Alice Régul"})
        cls.bob = env["res.partner"].create({"name": "Bob Régul"})
        cls.droit_bob = env["coproerp.droit"].create(
            {"personne_id": cls.bob.id, "lot_id": cls.lot2.id, "type_droit": "proprietaire"})
        env["coproerp.droit"].create({"personne_id": cls.alice.id, "lot_id": cls.lot1.id, "type_droit": "proprietaire"})
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
        # Quatre appels trimestriels comptabilisés : 8 000 € (Alice 4 800, Bob 3 200)
        cls.budget.action_generer_appels_budget_tous()
        cls.appels = env["coproerp.appel.charge"].search([("budget_origine_id", "=", cls.budget.id)])
        cls.appels.action_comptabiliser()
        # Fonds de travaux : ne doit pas entrer dans la régularisation
        cls.budget.action_generer_appel_fonds_suivant()
        env["coproerp.appel.charge"].search([
            ("budget_id", "=", cls.budget.id), ("type_appel", "=", "fonds_travaux")]).action_comptabiliser()
        cls.fournisseur = env["res.partner"].create({"name": "Fournisseur Régul"})
        Nature = env["coproerp.nature.depense"]
        cls.n615 = Nature.search([("code", "=", "615000")])
        cls.n616 = Nature.search([("code", "=", "616000")])
        cls.n671 = Nature.search([("code", "=", "671000")])

    # ---------------------------------------------------------------
    def _facture(self, lignes, ref, jour=date(2026, 6, 1), **vals):
        facture = self.env["coproerp.depense"].create({
            "copropriete_id": self.copro.id, "fournisseur_id": self.fournisseur.id,
            "reference_fournisseur": ref, "date_facture": jour,
            "ligne_ids": [Command.create({"nature_id": n.id, "repartition_id": c.id, "montant": m})
                          for n, c, m in lignes],
            **vals,
        })
        facture.action_valider()
        return facture

    def _regul(self):
        regul = self.env["coproerp.regularisation"].create({"budget_id": self.budget.id})
        regul.action_calculer()
        return regul

    def _compte(self, regul, personne):
        return regul.compte_ids.filtered(lambda c: c.personne_id == personne)

    def _solde(self, code, partner=None):
        dom = [("company_id", "=", self.company.id), ("account_id", "=", self.copro._compte(code).id),
               ("parent_state", "=", "posted")]
        if partner:
            dom.append(("partner_id", "=", partner.id))
        return round(sum(self.env["account.move.line"].search(dom).mapped("balance")), 2)

    # ---------------------------------------------------------------
    def test_repartition_au_centime(self):
        parts = {"a": 1, "b": 1, "c": 1}
        quotes = repartir(100.0, parts, 3, True)
        self.assertAlmostEqual(sum(quotes.values()), 100.0)
        self.assertEqual(sorted(quotes.values()), [33.33, 33.33, 33.34])
        quotes = repartir(-100.0, parts, 3, True)
        self.assertAlmostEqual(sum(quotes.values()), -100.0)
        # Clé incomplète : pas de redistribution des centimes
        quotes = repartir(100.0, {"a": 1}, 3, False)
        self.assertEqual(quotes, {"a": 33.33})

    def test_calcul_insuffisance(self):
        self._facture([(self.n615, self.cle, 3000.0), (self.n616, self.cle, 6000.0)], "F-1")
        regul = self._regul()
        self.assertEqual(regul.etat, "calculee")
        alice = self._compte(regul, self.alice)
        bob = self._compte(regul, self.bob)
        self.assertAlmostEqual(alice.charges, 5400.0)
        self.assertAlmostEqual(alice.provisions, 4800.0)
        self.assertAlmostEqual(alice.solde, 600.0)
        self.assertAlmostEqual(bob.solde, 400.0)
        self.assertAlmostEqual(regul.total_depenses, 9000.0)
        self.assertAlmostEqual(regul.total_provisions, 8000.0)
        details = alice.ligne_ids.detail_ids
        self.assertAlmostEqual(details.filtered(lambda d: d.code == "615000").quote_part, 1800.0)
        # Rien n'est comptabilisé avant validation
        self.assertFalse(regul.move_id)

    def test_comptabilisation_et_lettrage(self):
        self._facture([(self.n615, self.cle, 9000.0)], "F-2")
        # Alice a versé 5 000 €
        self.env["coproerp.reglement"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "date": date(2026, 9, 1), "montant": 5000.0}).action_valider()
        regul = self._regul()
        regul.action_comptabiliser()
        self.assertEqual(regul.etat, "comptabilisee")
        self.assertEqual(regul.move_id.journal_id.code, "OD")
        self.assertEqual(regul.move_id.date, date(2026, 12, 31))
        # 701 = provisions (8 000) + régularisation (1 000) = charges (9 000)
        self.assertAlmostEqual(self._solde("701000"), -9000.0)
        self.assertAlmostEqual(self._solde("615000"), 9000.0)
        # Les 5 000 € ont soldé les 4 appels (4 800) et le fonds de travaux (60) ;
        # les 140 € versés d'avance s'imputent sur la régularisation de 600 €.
        self.assertAlmostEqual(self._solde("450010", self.alice), 460.0)
        ligne = regul.move_id.line_ids.filtered(lambda l: l.partner_id == self.alice)
        self.assertAlmostEqual(ligne.amount_residual, 460.0)

    def test_excedent_en_faveur(self):
        self._facture([(self.n615, self.cle, 7000.0)], "F-3")
        regul = self._regul()
        self.assertAlmostEqual(self._compte(regul, self.alice).solde, -600.0)
        regul.action_comptabiliser()
        # Le crédit s'impute sur les appels encore dus
        self.assertAlmostEqual(self._solde("450010", self.alice), 4200.0)
        self.assertAlmostEqual(self._solde("701000"), -7000.0)

    def test_hors_budget_et_fonds_travaux_exclus(self):
        travaux = self.env["coproerp.travaux"].create({
            "copropriete_id": self.copro.id, "name": "Toiture",
            "date_vote": date(2026, 3, 1), "montant_vote": 30000.0,
        })
        self._facture([(self.n671, self.cle, 10000.0)], "T-1", travaux_id=travaux.id)
        self._facture([(self.n615, self.cle, 8000.0)], "F-4")
        regul = self._regul()
        self.assertAlmostEqual(regul.total_depenses, 8000.0)
        self.assertAlmostEqual(regul.total_provisions, 8000.0)
        self.assertAlmostEqual(regul.total_solde, 0.0)

    def test_coproprietaire_a_la_date_d_approbation(self):
        """Art. 6-2 du décret de 1967 : le solde va à celui qui est copropriétaire
        à la date d'approbation des comptes."""
        self._facture([(self.n615, self.cle, 9000.0)], "F-5")
        claire = self.env["res.partner"].create({"name": "Claire Acquéreur"})
        self.droit_bob.date_fin = date(2027, 2, 28)
        self.env["coproerp.droit"].create({
            "personne_id": claire.id, "lot_id": self.lot2.id, "type_droit": "proprietaire",
            "date_debut": date(2027, 3, 1)})
        regul = self.env["coproerp.regularisation"].create({
            "budget_id": self.budget.id, "date_attribution": date(2027, 4, 15)})
        regul.action_calculer()
        self.assertTrue(self._compte(regul, claire))
        self.assertFalse(self._compte(regul, self.bob))
        self.assertAlmostEqual(self._compte(regul, claire).solde, 400.0)

    def test_decompte_pdf(self):
        self._facture([(self.n615, self.cle, 3000.0), (self.n616, self.cle, 6000.0)], "F-6")
        regul = self._regul()
        compte = self._compte(regul, self.alice)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_regularisation.report_decompte", compte.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("DÉCOMPTE INDIVIDUEL DE CHARGES", html)
        self.assertIn("PROJET", html)
        self.assertIn("COMPLÉMENT À VOTRE CHARGE", html)
        self.assertIn("CHARGES GÉNÉRALES", html)

    def test_annulation_et_verrou_exercice(self):
        self._facture([(self.n615, self.cle, 9000.0)], "F-7")
        regul = self._regul()
        regul.action_comptabiliser()
        # Exercice régularisé : une nouvelle facture de 2026 est refusée
        facture = self.env["coproerp.depense"].create({
            "copropriete_id": self.copro.id, "fournisseur_id": self.fournisseur.id,
            "reference_fournisseur": "TARD", "date_facture": date(2026, 9, 15),
            "ligne_ids": [Command.create({"nature_id": self.n615.id, "repartition_id": self.cle.id,
                                          "montant": 50.0})],
        })
        with self.assertRaises(UserError):
            facture.action_valider()
        # Une seule régularisation active par exercice
        with self.assertRaises(Exception):
            self.env["coproerp.regularisation"].create({"budget_id": self.budget.id})
        regul.action_annuler()
        self.assertEqual(regul.etat, "annulee")
        self.assertAlmostEqual(self._solde("701000"), -8000.0)
        facture.action_valider()
        self.assertEqual(facture.etat, "validee")

    def test_charge_sans_cle_bloque_le_calcul(self):
        from odoo import Command as C
        move = self.env["account.move"].with_company(self.company).create({
            "move_type": "entry",
            "journal_id": self.copro._journal("od").id,
            "date": date(2026, 5, 5),
            "line_ids": [
                C.create({"account_id": self.copro._compte("615000").id, "name": "OD sans clé", "debit": 10.0}),
                C.create({"account_id": self.copro._compte("401000").id, "name": "OD sans clé",
                          "credit": 10.0, "partner_id": self.fournisseur.id}),
            ],
        })
        move.action_post()
        regul = self.env["coproerp.regularisation"].create({"budget_id": self.budget.id})
        with self.assertRaises(UserError):
            regul.action_calculer()
