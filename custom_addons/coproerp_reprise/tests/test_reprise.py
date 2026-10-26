"""Tests de la reprise des soldes.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_reprise \
        --test-tags /coproerp_reprise --stop-after-init
"""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_reprise")
class TestReprise(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Reprise", "street": "9 rue R", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.alice = env["res.partner"].create({"name": "Alice Reprise"})
        cls.bob = env["res.partner"].create({"name": "Bob Reprise"})
        for numero, personne in (("1", cls.alice), ("2", cls.bob)):
            lot = env["coproerp.lot"].create({"numero": numero, "designation": "Appartement", "batiment_id": bat.id})
            env["coproerp.droit"].create({"personne_id": personne.id, "lot_id": lot.id, "type_droit": "proprietaire"})
        cls.copro.action_creer_dossier_comptable()
        cls.company = cls.copro.company_id
        cls.edf = env["res.partner"].create({"name": "EDF Reprise"})

    def _reprise(self, **vals):
        reprise = self.env["coproerp.reprise"].create({
            "copropriete_id": self.copro.id, "date_reprise": date(2025, 12, 31), "solde_banque": 5000.0, **vals,
        })
        reprise.action_charger_coproprietaires()
        reprise.coproprietaire_ids.filtered(lambda l: l.personne_id == self.alice).write(
            {"solde": 800.0, "fonds_travaux": 300.0, "avance": 100.0})
        reprise.coproprietaire_ids.filtered(lambda l: l.personne_id == self.bob).write(
            {"solde": -200.0, "fonds_travaux": 200.0, "avance": 100.0})
        reprise.write({"facture_ids": [Command.create({
            "fournisseur_id": self.edf.id, "reference": "EDF-12", "date_facture": date(2025, 12, 15),
            "montant": 1500.0})]})
        return reprise

    def _solde(self, code, partner=None):
        compte = (self.copro._journal("banque").default_account_id if code == "banque"
                  else self.copro._compte(code))
        dom = [("company_id", "=", self.company.id), ("account_id", "=", compte.id),
               ("parent_state", "=", "posted")]
        if partner:
            dom.append(("partner_id", "=", partner.id))
        return round(sum(self.env["account.move.line"].search(dom).mapped("balance")), 2)

    # ---------------------------------------------------------------
    def test_ecart_bloque_la_comptabilisation(self):
        reprise = self._reprise()
        self.assertEqual(len(reprise.coproprietaire_ids), 2)
        # Actif 5 000 + 800 = 5 800 ; passif 200 + 500 + 200 + 1 500 = 2 400
        self.assertAlmostEqual(reprise.ecart, 3400.0)
        with self.assertRaises(UserError):
            reprise.action_comptabiliser()

    def test_reprise_complete(self):
        reprise = self._reprise()
        reprise.write({"autre_ids": [Command.create({
            "code_compte": "102000", "libelle": "Provisions pour travaux décidés", "credit": 3400.0})]})
        self.assertAlmostEqual(reprise.ecart, 0.0)
        reprise.action_comptabiliser()
        self.assertEqual(reprise.etat, "validee")
        self.assertAlmostEqual(self._solde("banque"), 5000.0)
        self.assertAlmostEqual(self._solde("450010", self.alice), 800.0)
        self.assertAlmostEqual(self._solde("450010", self.bob), -200.0)
        self.assertAlmostEqual(self._solde("105000", self.alice), -300.0)
        self.assertAlmostEqual(self._solde("102000"), -3400.0)
        self.assertAlmostEqual(self._solde("471000"), 0.0)
        self.assertAlmostEqual(self._solde("401000", self.edf), -1500.0)
        # Les fonds apparaissent sur les relevés et avis du copropriétaire
        fonds = self.copro.fonds_du_coproprietaire(self.alice)
        self.assertAlmostEqual(fonds["fonds_travaux"], 300.0)
        self.assertAlmostEqual(fonds["fonds_roulement"], 100.0)
        releve = self.copro.releve_compte(self.alice, None, date(2026, 1, 31))
        self.assertAlmostEqual(releve["solde"], 800.0)
        # La facture reprise se paie par le circuit habituel
        facture = reprise.depense_ids
        self.assertEqual(facture.etat, "validee")
        self.assertAlmostEqual(facture.montant_total, 1500.0)
        self.assertAlmostEqual(facture.montant_restant, 1500.0)
        paiement = self.env["coproerp.depense.paiement"].create({
            "depense_id": facture.id, "date": date(2026, 1, 20), "montant": 1500.0})
        paiement.action_valider()
        self.assertTrue(facture.est_payee)
        # Le règlement d'Alice s'impute sur le solde repris
        self.env["coproerp.reglement"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "date": date(2026, 1, 15), "montant": 800.0}).action_valider()
        self.assertAlmostEqual(self._solde("450010", self.alice), 0.0)
        # Une seconde reprise est refusée ; la reprise ne se modifie plus
        with self.assertRaises(UserError):
            reprise.solde_banque = 1.0
        autre = self._reprise()
        autre.write({"autre_ids": [Command.create({"code_compte": "102000", "credit": 3400.0})]})
        with self.assertRaises(UserError):
            autre.action_comptabiliser()
        # Annulation impossible une fois des règlements imputés
        with self.assertRaises(UserError):
            reprise.action_annuler()

    def test_annulation(self):
        reprise = self._reprise()
        reprise.write({"autre_ids": [Command.create({"code_compte": "102000", "credit": 3400.0})]})
        reprise.action_comptabiliser()
        reprise.action_annuler()
        self.assertEqual(reprise.etat, "annulee")
        self.assertEqual(reprise.depense_ids.etat, "annulee")
        self.assertAlmostEqual(self._solde("banque"), 0.0)
        self.assertAlmostEqual(self._solde("401000", self.edf), 0.0)
        self.assertAlmostEqual(self._solde("450010", self.alice), 0.0)

    def test_compte_inconnu(self):
        reprise = self._reprise()
        reprise.write({"autre_ids": [Command.create({"code_compte": "998877", "credit": 3400.0})]})
        with self.assertRaises(UserError):
            reprise.action_comptabiliser()
