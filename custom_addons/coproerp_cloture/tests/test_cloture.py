"""Tests de la clôture de l'exercice et des annexes comptables.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_cloture \
        --test-tags /coproerp_cloture --stop-after-init
"""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_cloture")
class TestCloture(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Clôture", "street": "5 rue C", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        lot1 = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        lot2 = env["coproerp.lot"].create({"numero": "2", "designation": "Appartement", "batiment_id": bat.id})
        cls.alice = env["res.partner"].create({"name": "Alice Clôture"})
        cls.bob = env["res.partner"].create({"name": "Bob Clôture"})
        env["coproerp.droit"].create({"personne_id": cls.alice.id, "lot_id": lot1.id, "type_droit": "proprietaire"})
        env["coproerp.droit"].create({"personne_id": cls.bob.id, "lot_id": lot2.id, "type_droit": "proprietaire"})
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot1.id, "tantiemes": 600})
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot2.id, "tantiemes": 400})
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
        cls.budget.action_generer_appel_fonds_suivant()
        env["coproerp.appel.charge"].search([
            ("budget_id", "=", cls.budget.id), ("type_appel", "=", "fonds_travaux")]).action_comptabiliser()
        cls.fournisseur = env["res.partner"].create({"name": "Fournisseur Clôture"})
        Nature = env["coproerp.nature.depense"]
        cls.n615 = Nature.search([("code", "=", "615000")])
        cls.n616 = Nature.search([("code", "=", "616000")])
        cls.n671 = Nature.search([("code", "=", "671000")])
        cls.travaux = env["coproerp.travaux"].create({
            "copropriete_id": cls.copro.id, "name": "Ravalement",
            "date_vote": date(2026, 3, 1), "montant_vote": 30000.0, "etat": "en_cours",
        })
        # Charges courantes 9 000 € (budget 8 000 €) et travaux 2 000 €
        cls._facture([(cls.n615, 3000.0), (cls.n616, 6000.0)], "C-1")
        cls._facture([(cls.n671, 2000.0)], "C-T1", travaux_id=cls.travaux.id)
        env["coproerp.reglement"].create({
            "copropriete_id": cls.copro.id, "personne_id": cls.alice.id,
            "date": date(2026, 9, 1), "montant": 5000.0}).action_valider()

    @classmethod
    def _facture(cls, lignes, ref, **vals):
        facture = cls.env["coproerp.depense"].create({
            "copropriete_id": cls.copro.id, "fournisseur_id": cls.fournisseur.id,
            "reference_fournisseur": ref, "date_facture": date(2026, 6, 1),
            "ligne_ids": [Command.create({"nature_id": n.id, "repartition_id": cls.cle.id, "montant": m})
                          for n, m in lignes],
            **vals,
        })
        facture.action_valider()
        return facture

    def _preparer(self):
        """Mise en réserve du fonds de travaux puis régularisation des charges."""
        self.copro._mettre_en_reserve_fonds_travaux(date(2026, 12, 31))
        regul = self.env["coproerp.regularisation"].create({"budget_id": self.budget.id})
        regul.action_calculer()
        regul.action_comptabiliser()
        return self.env["coproerp.cloture"].create({"budget_id": self.budget.id})

    # ---------------------------------------------------------------
    def test_controles_avant_cloture(self):
        cloture = self.env["coproerp.cloture"].create({"budget_id": self.budget.id})
        self.assertFalse(cloture.controles_ok)
        self.assertIn("régularisation", cloture.controles)
        self.assertIn("705", cloture.controles)
        with self.assertRaises(UserError):
            cloture.action_cloturer()
        self.assertEqual(cloture.etat, "brouillon")

    def test_annexe1_equilibree(self):
        cloture = self._preparer()
        self.assertTrue(cloture.controles_ok, cloture.controles)
        a1 = cloture.donnees_annexes()["annexe1"]
        totaux = a1["totaux_n"]
        self.assertAlmostEqual(totaux["actif"], totaux["passif"], places=2)
        self.assertAlmostEqual(a1["n"].get("tresorerie_51", 0.0), 5000.0, places=2)
        self.assertGreater(a1["n"].get("fonds_105", 0.0), 0.0)
        # Les travaux payés ou dus (2 000 €) non encore appelés restent en attente (ligne 12)
        self.assertAlmostEqual(a1["n"].get("attente_12", 0.0), -2000.0, places=2)
        # Fournisseur : 11 000 € de factures non payées
        self.assertAlmostEqual(a1["n"].get("dette_40", 0.0), 11000.0, places=2)

    def test_annexes_2_et_3(self):
        cloture = self._preparer()
        d = cloture.donnees_annexes()
        courant = d["annexe2"]["courant"]
        self.assertAlmostEqual(courant["total_charges"]["n"], 9000.0)
        self.assertAlmostEqual(courant["total_produits"]["n"], 8000.0)
        self.assertAlmostEqual(courant["solde"]["n"], 1000.0)
        self.assertAlmostEqual(d["annexe2"]["regularisation"]["n"], 1000.0)
        self.assertAlmostEqual(d["annexe2"]["budget"]["n"], 8000.0)
        self.assertEqual([g["classe"] for g in courant["charges"]], ["61"])
        self.assertAlmostEqual(d["annexe2"]["travaux"]["total_charges"]["n"], 2000.0)
        cles = d["annexe3"]["cles"]
        self.assertEqual(len(cles), 1)
        self.assertEqual(cles[0]["cle"], self.cle)
        self.assertAlmostEqual(cles[0]["n"], 9000.0)
        self.assertAlmostEqual(cles[0]["budget"]["n"], 8000.0)

    def test_annexes_4_et_5(self):
        cloture = self._preparer()
        d = cloture.donnees_annexes()
        self.assertEqual(len(d["annexe4"]), 1)
        self.assertEqual(d["annexe4"][0]["travaux"], self.travaux)
        self.assertAlmostEqual(d["annexe4"][0]["total_charges"]["n"], 2000.0)
        lignes = d["annexe5"]["lignes"]
        self.assertEqual(len(lignes), 1)
        self.assertAlmostEqual(lignes[0]["depenses"], 2000.0)
        self.assertAlmostEqual(lignes[0]["appels"], 0.0)
        # Le solde de l'annexe 5 se retrouve à la ligne 12 de l'annexe 1
        self.assertAlmostEqual(d["annexe5"]["total"]["solde"], d["annexe1"]["n"].get("attente_12", 0.0))

    def test_cloture_verrouille_l_exercice(self):
        cloture = self._preparer()
        cloture.action_cloturer()
        self.assertEqual(cloture.etat, "cloturee")
        self.assertEqual(self.company.fiscalyear_lock_date, date(2026, 12, 31))
        with self.assertRaises(UserError):
            cloture.unlink()
        move = self.env["account.move"].with_company(self.company).create({
            "move_type": "entry",
            "journal_id": self.copro._journal("od").id,
            "date": date(2026, 6, 15),
            "line_ids": [
                Command.create({"account_id": self.copro._compte("615000").id, "name": "Tardive",
                                "debit": 10.0}),
                Command.create({"account_id": self.copro._compte("401000").id, "name": "Tardive",
                                "credit": 10.0, "partner_id": self.fournisseur.id}),
            ],
        })
        try:
            move.action_post()
        except UserError:
            pass
        else:
            # Selon la version, Odoo reporte l'écriture après la date de verrouillage
            self.assertGreater(move.date, date(2026, 12, 31))

    def test_budgets_voisins(self):
        suivant = self.env["coproerp.budget.annuel"].create({
            "copropriete_id": self.copro.id, "exercice": 2027,
            "date_debut": date(2027, 1, 1), "date_fin": date(2027, 12, 31),
            "budget_previsionnel": 8500.0,
            "repartition_fonds_travaux_id": self.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": self.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 8500.0})],
        })
        action = self.budget.action_cloture()
        cloture = self.env["coproerp.cloture"].browse(action["res_id"])
        self.assertEqual(cloture.budget_en_cours_id, suivant)
        self.assertFalse(cloture.budget_precedent_id)
        d = cloture.donnees_annexes()
        self.assertAlmostEqual(d["annexe2"]["budget"]["en_cours"], 8500.0)
        self.assertIsNone(d["annexe2"]["budget"]["a_voter"])
        # Le bouton du budget rouvre la même clôture
        self.assertEqual(self.budget.action_cloture()["res_id"], cloture.id)

    def test_pdf_annexes(self):
        cloture = self._preparer()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_cloture.report_annexes", cloture.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("ANNEXE 1", "ANNEXE 2", "ANNEXE 3", "ANNEXE 4", "ANNEXE 5",
                      "PROJET", "Ravalement", "9 000,00"):
            self.assertIn(texte, html)
