"""Avoirs fournisseurs et paiement groupé de plusieurs factures."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CoproGestionCase


@tagged("post_install", "-at_install", "coproerp_gestion_courante")
class TestAvoirs(CoproGestionCase):

    def test_avoir_diminue_les_charges(self):
        facture = self._piece(1000.0, "F-100")
        facture.action_valider()
        self.assertAlmostEqual(self._solde("615000"), 1000.0)
        avoir = self._piece(200.0, "AV-100", type_piece="avoir", jour=date(2026, 3, 20))
        avoir.action_valider()
        self.assertEqual(avoir.etat, "validee")
        self.assertEqual(avoir.move_id.journal_id.code, "ACH")
        self.assertAlmostEqual(self._solde("615000"), 800.0)
        self.assertAlmostEqual(self._solde("401000", self.fournisseur), -800.0)
        ligne = avoir.move_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(ligne.coproerp_repartition_id, self.cle)
        self.env.invalidate_all()
        self.assertAlmostEqual(avoir.montant_restant, -200.0)
        with self.assertRaises(UserError):
            avoir.action_enregistrer_paiement()

    def test_avoir_impute_sur_la_facture_d_origine(self):
        facture = self._piece(1000.0, "F-101")
        facture.action_valider()
        avoir = self._piece(1000.0, "AV-101", type_piece="avoir", facture_origine_id=facture.id)
        avoir.action_valider()
        self.env.invalidate_all()
        self.assertTrue(facture.est_payee)
        self.assertTrue(avoir.est_payee)
        self.assertAlmostEqual(self._solde("401000", self.fournisseur), 0.0)

    def test_avoir_partiel_sur_facture_d_origine(self):
        facture = self._piece(1000.0, "F-102")
        facture.action_valider()
        avoir = self._piece(300.0, "AV-102", type_piece="avoir", facture_origine_id=facture.id)
        avoir.action_valider()
        self.env.invalidate_all()
        self.assertAlmostEqual(facture.montant_restant, 700.0)
        self.assertFalse(facture.est_payee)
        self.assertTrue(avoir.est_payee)

    def test_paiement_groupe(self):
        f1 = self._piece(1000.0, "F-201")
        f2 = self._piece(500.0, "F-202", jour=date(2026, 4, 2))
        avoir = self._piece(150.0, "AV-201", type_piece="avoir", jour=date(2026, 4, 5))
        (f1 | f2 | avoir).action_valider()
        groupe = self.env["coproerp.paiement.groupe"].create({
            "copropriete_id": self.copro.id, "fournisseur_id": self.fournisseur.id,
            "date": date(2026, 4, 30), "reference": "VIR-0430",
            "depense_ids": [(6, 0, (f1 | f2 | avoir).ids)],
        })
        self.assertTrue(groupe.name.startswith("PG/"))
        self.assertAlmostEqual(groupe.montant, 1350.0)
        banque_avant = self._solde("512000")
        groupe.action_valider()
        self.assertEqual(groupe.etat, "valide")
        self.assertEqual(groupe.move_id.journal_id.code, "BQ")
        self.env.invalidate_all()
        self.assertTrue(f1.est_payee and f2.est_payee and avoir.est_payee)
        self.assertAlmostEqual(self._solde("401000", self.fournisseur), 0.0)
        self.assertAlmostEqual(self._solde("512000"), round(banque_avant - 1350.0, 2))
        banque = groupe.move_id.line_ids.filtered(lambda l: l.account_id == self.copro._journal("banque").default_account_id)
        self.assertAlmostEqual(banque.credit, 1350.0)
        # Annulation : les factures redeviennent dues
        groupe.action_annuler()
        self.env.invalidate_all()
        self.assertEqual(groupe.etat, "annule")
        self.assertFalse(f1.est_payee)
        self.assertAlmostEqual(self._solde("401000", self.fournisseur), -1350.0)

    def test_paiement_groupe_compensation_sans_banque(self):
        facture = self._piece(400.0, "F-301")
        avoir = self._piece(400.0, "AV-301", type_piece="avoir")
        (facture | avoir).action_valider()
        groupe = self.env["coproerp.paiement.groupe"].create({
            "copropriete_id": self.copro.id, "fournisseur_id": self.fournisseur.id,
            "date": date(2026, 4, 30), "depense_ids": [(6, 0, (facture | avoir).ids)],
        })
        self.assertAlmostEqual(groupe.montant, 0.0)
        groupe.action_valider()
        self.assertEqual(groupe.move_id.journal_id.code, "OD")
        self.env.invalidate_all()
        self.assertTrue(facture.est_payee and avoir.est_payee)

    def test_avoirs_superieurs_refuses(self):
        facture = self._piece(100.0, "F-401")
        avoir = self._piece(300.0, "AV-401", type_piece="avoir")
        (facture | avoir).action_valider()
        groupe = self.env["coproerp.paiement.groupe"].create({
            "copropriete_id": self.copro.id, "fournisseur_id": self.fournisseur.id,
            "date": date(2026, 4, 30), "depense_ids": [(6, 0, (facture | avoir).ids)],
        })
        with self.assertRaises(UserError):
            groupe.action_valider()
