"""Tests de la saisie des dépenses.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_depenses \
        --test-tags /coproerp_depenses --stop-after-init
"""

from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install", "coproerp_depenses")
class TestDepenses(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Dépenses", "street": "3 rue Z", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        lot1 = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        lot2 = env["coproerp.lot"].create({"numero": "2", "designation": "Appartement", "batiment_id": bat.id})
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot1.id, "tantiemes": 600})
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot2.id, "tantiemes": 400})
        cls.cle_asc = env["coproerp.repartition"].create({
            "name": "Ascenseur", "copropriete_id": cls.copro.id,
            "type_repartition": "ascenseur_escalier", "total_tantiemes": 1000,
        })
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle_asc.id, "lot_id": lot2.id, "tantiemes": 1000})
        cls.budget = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": 2026,
            "date_debut": date(2026, 1, 1), "date_fin": date(2026, 12, 31),
            "budget_previsionnel": 10000.0,
            "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [
                (0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES", "montant_annuel": 8000.0}),
                (0, 0, {"repartition_id": cls.cle_asc.id, "designation": "ASCENSEUR", "montant_annuel": 2000.0}),
            ],
        })
        cls.copro.action_creer_dossier_comptable()
        cls.company = cls.copro.company_id
        cls.fournisseur = env["res.partner"].create({"name": "Entretien Services SARL"})
        cls.ascensoriste = env["res.partner"].create({"name": "Ascenseurs & Cie"})
        Nature = env["coproerp.nature.depense"]
        cls.n_entretien = Nature.search([("code", "=", "615000")])
        cls.n_assurance = Nature.search([("code", "=", "616000")])
        cls.n_maintenance = Nature.search([("code", "=", "614000")])
        cls.n_travaux = Nature.search([("code", "=", "671000")])

    # ---------------------------------------------------------------
    def _facture(self, fournisseur=None, ref="F-001", lignes=None, **vals):
        lignes = lignes or [(self.n_entretien, self.cle, 300.0), (self.n_assurance, self.cle, 1200.0)]
        return self.env["coproerp.depense"].create({
            "copropriete_id": self.copro.id,
            "fournisseur_id": (fournisseur or self.fournisseur).id,
            "reference_fournisseur": ref,
            "date_facture": date(2026, 3, 10),
            "date_echeance": date(2026, 4, 10),
            "ligne_ids": [Command.create({"nature_id": n.id, "repartition_id": c.id, "montant": m})
                          for n, c, m in lignes],
            **vals,
        })

    def _solde(self, code, partner=None):
        dom = [("company_id", "=", self.company.id), ("account_id", "=", self.copro._compte(code).id),
               ("parent_state", "=", "posted")]
        if partner:
            dom.append(("partner_id", "=", partner.id))
        return round(sum(self.env["account.move.line"].search(dom).mapped("balance")), 2)

    def _payer(self, depense, montant, jour=date(2026, 4, 5)):
        paiement = self.env["coproerp.depense.paiement"].create({
            "depense_id": depense.id, "date": jour, "montant": montant})
        paiement.action_valider()
        return paiement

    # ---------------------------------------------------------------
    def test_natures_chargees(self):
        self.assertTrue(self.n_entretien and self.n_assurance and self.n_travaux)
        self.assertTrue(self.n_travaux.travaux)
        self.assertFalse(self.n_entretien.travaux)

    def test_comptabilisation(self):
        facture = self._facture()
        self.assertEqual(facture.montant_total, 1500.0)
        self.assertEqual(facture.budget_id, self.budget)
        facture.action_valider()
        self.assertEqual(facture.etat, "validee")
        self.assertEqual(facture.move_id.journal_id.code, "ACH")
        self.assertEqual(facture.move_id.state, "posted")
        self.assertAlmostEqual(self._solde("615000"), 300.0)
        self.assertAlmostEqual(self._solde("616000"), 1200.0)
        self.assertAlmostEqual(self._solde("401000", self.fournisseur), -1500.0)
        ligne = facture.move_id.line_ids.filtered(lambda l: l.debit == 300.0)
        self.assertEqual(ligne.coproerp_repartition_id, self.cle)
        self.assertAlmostEqual(facture.montant_restant, 1500.0)
        # Verrouillage
        with self.assertRaises(UserError):
            facture.reference_fournisseur = "AUTRE"
        with self.assertRaises(UserError):
            facture.ligne_ids[:1].montant = 1.0
        with self.assertRaises(UserError):
            facture.unlink()

    def test_paiements_partiels(self):
        facture = self._facture()
        facture.action_valider()
        p1 = self._payer(facture, 500.0)
        self.assertEqual(p1.move_id.journal_id.code, "BQ")
        self.env.invalidate_all()
        self.assertAlmostEqual(facture.montant_restant, 1000.0)
        self.assertFalse(facture.est_payee)
        with self.assertRaises(UserError):
            self._payer(facture, 1000.01)
        self._payer(facture, 1000.0)
        self.env.invalidate_all()
        self.assertAlmostEqual(facture.montant_restant, 0.0)
        self.assertTrue(facture.est_payee)
        self.assertAlmostEqual(self._solde("401000", self.fournisseur), 0.0)
        self.assertAlmostEqual(self._solde("512000"), -1500.0)
        # Annulation d'un paiement : la facture redevient due
        p1.action_annuler()
        self.env.invalidate_all()
        self.assertEqual(p1.etat, "annule")
        self.assertFalse(facture.est_payee)
        self.assertAlmostEqual(facture.montant_restant, 500.0)

    def test_annulation_facture(self):
        facture = self._facture()
        facture.action_valider()
        paiement = self._payer(facture, 100.0)
        with self.assertRaises(UserError):
            facture.action_annuler()
        paiement.action_annuler()
        facture.action_annuler()
        self.assertEqual(facture.etat, "annulee")
        self.assertAlmostEqual(self._solde("615000"), 0.0)
        self.assertAlmostEqual(self._solde("401000", self.fournisseur), 0.0)
        # La même référence peut être ressaisie après annulation
        self._facture().action_valider()

    def test_doublon_refuse(self):
        self._facture(ref="F-77")
        with self.assertRaises(ValidationError):
            self._facture(ref="f-77")
        # Même numéro chez un autre fournisseur : accepté
        self._facture(fournisseur=self.ascensoriste, ref="F-77")

    def test_date_future_refusee(self):
        with self.assertRaises(ValidationError):
            self._facture(date_facture=date.today() + timedelta(days=2))

    def test_realise_du_budget(self):
        self._facture().action_valider()
        self._facture(fournisseur=self.ascensoriste, ref="A-1",
                      lignes=[(self.n_maintenance, self.cle_asc, 450.0)]).action_valider()
        lignes = self.budget.ligne_ids
        generale = lignes.filtered(lambda l: l.repartition_id == self.cle)
        ascenseur = lignes.filtered(lambda l: l.repartition_id == self.cle_asc)
        self.assertAlmostEqual(generale.montant_realise, 1500.0)
        self.assertAlmostEqual(generale.ecart_realise, 6500.0)
        self.assertAlmostEqual(ascenseur.montant_realise, 450.0)
        self.assertAlmostEqual(self.budget.total_realise, 1950.0)

    def test_travaux_hors_budget(self):
        with self.assertRaises(ValidationError):
            self._facture(ref="T-1", lignes=[(self.n_travaux, self.cle, 5000.0)])
        travaux = self.env["coproerp.travaux"].create({
            "copropriete_id": self.copro.id, "name": "Ravalement",
            "date_vote": date(2026, 2, 1), "montant_vote": 20000.0,
        })
        facture = self._facture(ref="T-1", lignes=[(self.n_travaux, self.cle, 5000.0)], travaux_id=travaux.id)
        facture.action_valider()
        ligne = facture.move_id.line_ids.filtered(lambda l: l.debit == 5000.0)
        self.assertTrue(ligne.coproerp_hors_budget)
        self.assertEqual(ligne.coproerp_travaux_id, travaux)
        generale = self.budget.ligne_ids.filtered(lambda l: l.repartition_id == self.cle)
        self.assertAlmostEqual(generale.montant_realise, 0.0)

    def test_extranet_releve_des_depenses(self):
        self._facture().action_valider()
        depenses = self.copro._extranet_depenses()
        self.assertEqual({d["compte"] for d in depenses}, {"615000", "616000"})

    def test_gestionnaire_sans_societe_cochee(self):
        principale = self.env.ref("base.main_company")
        gestionnaire = new_test_user(
            self.env, login="gestionnaire_depenses",
            groups="base.group_user,account.group_account_manager",
            company_id=principale.id,
            company_ids=[Command.set([principale.id, self.company.id])],
        )
        env_g = self.env(user=gestionnaire, context={"allowed_company_ids": [principale.id]})
        facture = self._facture().with_env(env_g)
        facture.action_valider()
        paiement = env_g["coproerp.depense.paiement"].create({
            "depense_id": facture.id, "date": date(2026, 4, 5), "montant": 1500.0})
        paiement.action_valider()
        self.env.invalidate_all()
        self.assertTrue(facture.sudo().est_payee)
