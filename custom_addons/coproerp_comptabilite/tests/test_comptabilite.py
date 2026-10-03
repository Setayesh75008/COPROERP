"""Tests de la comptabilité des copropriétés.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_comptabilite \
        --test-tags /coproerp_comptabilite --stop-after-init
"""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install", "coproerp_comptabilite")
class TestComptabilite(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Compta", "street": "1 rue X", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.lot1 = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        cls.lot2 = env["coproerp.lot"].create({"numero": "2", "designation": "Appartement", "batiment_id": bat.id})
        cls.alice = env["res.partner"].create({"name": "Alice Compta"})
        cls.bob = env["res.partner"].create({"name": "Bob Compta"})
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

    # ---------------------------------------------------------------
    def _appels(self, **dom):
        return self.env["coproerp.appel.charge"].search([(k, "=", v) for k, v in dom.items()])

    def _solde(self, partner, code):
        compte = self.copro._compte(code)
        lignes = self.env["account.move.line"].search([
            ("company_id", "=", self.company.id), ("account_id", "=", compte.id),
            ("partner_id", "=", partner.id), ("parent_state", "=", "posted"),
        ])
        return round(sum(lignes.mapped("balance")), 2)

    def _premier_trimestre(self):
        self.budget.action_generer_appel_budget_suivant()
        return self._appels(budget_origine_id=self.budget.id)

    # ---------------------------------------------------------------
    def test_dossier_comptable(self):
        self.assertTrue(self.company)
        self.assertEqual(self.company.chart_template, "copro_fr")
        for code in ("450010", "450050", "701000", "705000", "105000", "512000", "401000", "615000"):
            self.assertTrue(self.copro._compte(code), code)
        for code in ("APF", "BQ", "ACH", "OD"):
            journal = self.copro._journal({"APF": "appels", "BQ": "banque", "ACH": "achats", "OD": "od"}[code])
            self.assertTrue(journal.restrict_mode_hash_table, code)
        with self.assertRaises(UserError):
            self.copro.action_creer_dossier_comptable()

    def test_comptabilisation_appel(self):
        appels = self._premier_trimestre()
        appels.action_comptabiliser()
        alice = appels.filtered(lambda a: a.personne_id == self.alice)
        self.assertEqual(alice.etat_comptable, "comptabilise")
        self.assertEqual(alice.move_id.state, "posted")
        self.assertEqual(alice.move_id.journal_id.code, "APF")
        self.assertEqual(alice.move_id.date, date(2026, 1, 1))
        # 2000 € / trimestre, Alice 60 %
        self.assertAlmostEqual(self._solde(self.alice, "450010"), 1200.0)
        self.assertAlmostEqual(self._solde(self.alice, "701000"), -1200.0)
        # Verrouillage
        with self.assertRaises(UserError):
            alice.groupe_ids.poste_ids[:1].total_a_repartir = 1.0
        with self.assertRaises(UserError):
            alice.unlink()

    def test_fonds_travaux(self):
        self.budget.action_generer_appel_fonds_suivant()
        appels = self._appels(budget_id=self.budget.id, type_appel="fonds_travaux")
        appels.action_comptabiliser()
        # 5 % de 8000 = 400 / an -> 100 par trimestre ; Alice 60 %
        self.assertAlmostEqual(self._solde(self.alice, "450050"), 60.0)
        self.assertAlmostEqual(self._solde(self.alice, "705000"), -60.0)
        wizard = self.env["coproerp.mise.en.reserve"].create({
            "copropriete_id": self.copro.id, "date_cloture": date(2026, 12, 31)})
        wizard.action_valider()
        self.assertAlmostEqual(self._solde(self.alice, "705000"), 0.0)
        self.assertAlmostEqual(self._solde(self.alice, "105000"), -60.0)
        fonds = self.copro.fonds_du_coproprietaire(self.alice)
        self.assertAlmostEqual(fonds["fonds_travaux"], 60.0)

    def test_reglements_imputation_et_avance(self):
        appels = self._premier_trimestre()
        appels.action_comptabiliser()
        alice = appels.filtered(lambda a: a.personne_id == self.alice)
        Reglement = self.env["coproerp.reglement"]
        r1 = Reglement.create({"copropriete_id": self.copro.id, "personne_id": self.alice.id,
                               "date": date(2026, 1, 5), "montant": 1000.0})
        r1.action_valider()
        self.assertEqual(r1.move_id.journal_id.code, "BQ")
        self.assertAlmostEqual(alice.montant_restant, 200.0)
        r2 = Reglement.create({"copropriete_id": self.copro.id, "personne_id": self.alice.id,
                               "date": date(2026, 2, 5), "montant": 500.0})
        r2.action_valider()
        self.env.invalidate_all()
        self.assertAlmostEqual(alice.montant_restant, 0.0)
        self.assertAlmostEqual(self._solde(self.alice, "450010"), -300.0, msg="300 € versés d'avance")
        # Échéance suivante : l'avance est imputée automatiquement
        self.budget.action_generer_appel_budget_suivant()
        suivant = self._appels(budget_origine_id=self.budget.id, numero_appel_budget=2,
                               personne_id=self.alice.id)
        suivant.action_comptabiliser()
        self.assertAlmostEqual(suivant.montant_restant, 900.0)
        # Validé = non modifiable ; annulation par contre-passation
        with self.assertRaises(UserError):
            r2.montant = 1.0
        r2.action_annuler()
        self.assertEqual(r2.etat, "annule")
        self.assertAlmostEqual(self._solde(self.alice, "450010"), 1200.0 + 1200.0 - 1000.0)

    def test_annulation_appel(self):
        appels = self._premier_trimestre()
        appels.action_comptabiliser()
        bob = appels.filtered(lambda a: a.personne_id == self.bob)
        bob.action_annuler_comptabilisation()
        self.assertEqual(bob.etat_comptable, "annule")
        self.assertTrue(bob.move_annulation_id)
        self.assertAlmostEqual(self._solde(self.bob, "450010"), 0.0)

    def test_releve_sur_avis(self):
        appels = self._premier_trimestre()
        appels.action_comptabiliser()
        self.env["coproerp.reglement"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "date": date(2026, 2, 1), "montant": 700.0}).action_valider()
        self.budget.action_generer_appel_budget_suivant()
        suivant = self._appels(budget_origine_id=self.budget.id, numero_appel_budget=2,
                               personne_id=self.alice.id)
        avis = suivant.avis_regroupes()[0]
        self.assertTrue(avis["projet"])
        releve = avis["releve"]
        self.assertEqual(releve["date_precedent"], date(2026, 1, 1))
        self.assertAlmostEqual(releve["solde_precedent"], 1200.0)
        # 1200 - 700 + 1200 (échéance 2, projet)
        self.assertAlmostEqual(releve["solde"], 1700.0)
        self.assertAlmostEqual(avis["a_regler"], 1700.0)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_appel_edition.report_avis_appel", suivant.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("SOLDE AU", html)
        self.assertIn("PROJET", html)

    def test_releve_inclut_reglements_posterieurs_a_l_echeance(self):
        """Avis imprimé après l'échéance : les règlements déjà reçus (même
        datés après l'échéance) doivent apparaître dans le relevé."""
        appels = self._premier_trimestre()
        appels.action_comptabiliser()
        self.budget.action_generer_appel_budget_suivant()
        suivant = self._appels(budget_origine_id=self.budget.id, numero_appel_budget=2,
                               personne_id=self.alice.id)
        # Règlement daté après l'échéance du 2e trimestre (01/04/2026)
        self.env["coproerp.reglement"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "date": date(2026, 5, 15), "montant": 1500.0}).action_valider()
        avis = suivant.with_context(tz="Europe/Paris").avis_regroupes()[0]
        releve = avis["releve"]
        # 1200 (T1) - 1500 + 1200 (T2, projet) = 900, si l'avis est imprimé après le 15/05/2026
        if releve["date_solde"] >= date(2026, 5, 15):
            self.assertAlmostEqual(releve["solde"], 900.0)
            self.assertAlmostEqual(avis["a_regler"], 900.0)

    def test_extranet_solde_reel_et_cloisonnement(self):
        appels = self._premier_trimestre()
        appels.action_comptabiliser()
        mouvements = self.copro._extranet_mouvements([self.alice.id])
        self.assertAlmostEqual(sum(m["debit"] - m["credit"] for m in mouvements), 1200.0)
        # Un copropriétaire (portail) ne peut obtenir que ses propres écritures
        user_alice = new_test_user(self.env, login="alice_compta", groups="base.group_portal",
                                   partner_id=self.alice.id)
        vues = self.copro.with_user(user_alice)._extranet_mouvements([self.alice.id, self.bob.id])
        self.assertEqual({m["personne_id"] for m in vues}, {self.alice.id})
        vues = self.copro.with_user(user_alice)._extranet_mouvements()
        self.assertEqual({m["personne_id"] for m in vues}, {self.alice.id})

    def _plan_fr_disponible(self):
        return "fr" in self.env["account.chart.template"]._get_chart_template_mapping(get_all=True)

    def test_plan_general_ne_remplace_pas_le_plan_copro(self):
        """Odoo peut charger le plan général « fr » sur une société française
        au moment de l'enregistrement : il doit être ignoré pour un dossier
        de copropriété."""
        if not self._plan_fr_disponible():
            self.skipTest("Plan comptable français (l10n_fr) non installé")
        self.assertTrue(self.company.coproerp_dossier_copro)
        self.env["account.chart.template"]._load("fr", self.company, install_demo=False)
        self.assertEqual(self.company.chart_template, "copro_fr")
        self.assertTrue(self.copro._compte("450010"))
        self.assertTrue(self.copro._journal("appels"))

    def test_reparation_dossier(self):
        if not self._plan_fr_disponible():
            self.skipTest("Plan comptable français (l10n_fr) non installé")
        copro = self.env["coproerp.copropriete"].create({
            "name": "Résidence à réparer", "street": "2 rue Y", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        copro.action_creer_dossier_comptable()
        company = copro.company_id
        # Reproduit le dossier abîmé : plan général chargé à la place
        company.coproerp_dossier_copro = False
        self.env["account.chart.template"].try_loading("fr", company, install_demo=False)
        self.assertEqual(company.chart_template, "fr")
        self.assertTrue(copro.dossier_a_reparer)
        with self.assertRaises(UserError):
            copro._compte("450010")
        copro.action_reparer_dossier_comptable()
        copro.invalidate_recordset(["dossier_a_reparer"])
        self.assertEqual(company.chart_template, "copro_fr")
        self.assertFalse(copro.dossier_a_reparer)
        self.assertTrue(copro._compte("450010"))
        banque = copro._journal("banque")
        self.assertTrue(banque.restrict_mode_hash_table)
        self.assertTrue(banque.bank_account_id)

    def test_gestionnaire_sans_societe_cochee(self):
        """Un gestionnaire qui n'a coché que la société principale dans le
        sélecteur doit pouvoir comptabiliser et imputer un règlement."""
        principale = self.env.ref("base.main_company")
        gestionnaire = new_test_user(
            self.env, login="gestionnaire_compta",
            groups="base.group_user,account.group_account_manager",
            company_id=principale.id,
            company_ids=[Command.set([principale.id, self.company.id])],
        )
        env_g = self.env(user=gestionnaire, context={"allowed_company_ids": [principale.id]})
        self.budget.action_generer_appel_budget_suivant()
        appels = self._appels(budget_origine_id=self.budget.id).with_env(env_g)
        appels.action_comptabiliser()
        reglement = env_g["coproerp.reglement"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "date": date(2026, 1, 5), "montant": 1000.0})
        reglement.action_valider()
        self.assertNotIn("avance", reglement.imputation)
        self.env.invalidate_all()
        alice = appels.filtered(lambda a: a.personne_id == self.alice).sudo()
        self.assertAlmostEqual(alice.montant_restant, 200.0)

    def test_releve_des_depenses(self):
        move = self.env["account.move"].with_company(self.company).create({
            "move_type": "entry",
            "journal_id": self.copro._journal("achats").id,
            "date": date(2026, 3, 1),
            "ref": "Facture entretien",
            "line_ids": [
                Command.create({"account_id": self.copro._compte("615000").id, "name": "Réparation porte",
                                "debit": 250.0}),
                Command.create({"account_id": self.copro._compte("401000").id, "name": "Réparation porte",
                                "credit": 250.0, "partner_id": self.bob.id}),
            ],
        })
        move.action_post()
        depenses = self.copro._extranet_depenses()
        self.assertEqual(len(depenses), 1)
        self.assertEqual(depenses[0]["compte"], "615000")
        self.assertAlmostEqual(depenses[0]["debit"], 250.0)
