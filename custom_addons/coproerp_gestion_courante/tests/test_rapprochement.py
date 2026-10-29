"""Rapprochement bancaire : import CSV / OFX, pointage, création des écritures manquantes, état."""

import base64
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models.rapprochement import analyser_csv, analyser_ofx, lire_montant
from .common import CoproGestionCase

CSV = """Relevé du compte courant;;;
Date opération;Libellé;Débit;Crédit
05/04/2026;VIR SEPA MARTINEAU ALICE CHARGES T2;;1 200,00
08/04/2026;VIR SEPA BOB DURANDAL;;500,00
15/04/2026;PRLV PLOMBERIE LAVOISIER;-360,00;
30/04/2026;FRAIS TENUE DE COMPTE;12,50;
""".encode("cp1252")

OFX = b"""OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260405<TRNAMT>1200.00<FITID>A1<NAME>VIR MARTINEAU ALICE
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260430<TRNAMT>-12.50<FITID>A2<NAME>FRAIS TENUE DE COMPTE
</BANKTRANLIST><LEDGERBAL><BALAMT>1187.50<DTASOF>20260430</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


@tagged("post_install", "-at_install", "coproerp_gestion_courante")
class TestRapprochement(CoproGestionCase):

    def _releve(self, contenu, nom, **vals):
        return self.env["coproerp.releve.bancaire"].create({
            "copropriete_id": self.copro.id, "fichier": base64.b64encode(contenu), "fichier_nom": nom, **vals})

    def test_analyse_des_fichiers(self):
        self.assertAlmostEqual(lire_montant("1 234,56"), 1234.56)
        self.assertAlmostEqual(lire_montant("-1.234,56"), -1234.56)
        self.assertAlmostEqual(lire_montant("1,234.56"), 1234.56)
        operations, solde = analyser_csv(CSV)
        self.assertIsNone(solde)
        self.assertEqual([o["montant"] for o in operations], [1200.0, 500.0, -360.0, -12.5])
        self.assertEqual(operations[0]["date"], date(2026, 4, 5))
        operations, solde = analyser_ofx(OFX)
        self.assertEqual([o["montant"] for o in operations], [1200.0, -12.5])
        self.assertAlmostEqual(solde, 1187.5)
        with self.assertRaises(UserError):
            analyser_csv(b"a;b;c\n1;2;3\n")

    def test_pointage_et_creations(self):
        # Écritures déjà saisies : le règlement d'Alice (date décalée de 2 jours) et la facture du plombier
        reglement = self._reglement(self.alice, date(2026, 4, 3), 1200.0)
        facture = self._piece(360.0, "F-PL-1")
        facture.action_valider()
        releve = self._releve(CSV, "releve.csv", solde_final=1327.5)
        self.assertTrue(releve.name.startswith("RB/"))
        releve.action_importer()
        self.assertEqual(len(releve.ligne_ids), 4)
        self.assertEqual((releve.date_debut, releve.date_fin), (date(2026, 4, 5), date(2026, 4, 30)))
        l_alice, l_bob, l_plombier, l_frais = releve.ligne_ids.sorted("date")
        self.assertEqual(l_alice.etat, "pointe")
        self.assertEqual(l_alice.move_line_id.move_id, reglement.move_id)
        # Bob : virement non saisi, le copropriétaire est reconnu dans le libellé
        self.assertEqual(l_bob.etat, "a_pointer")
        self.assertEqual(l_bob.personne_id, self.bob)
        # Plombier : facture de même montant proposée
        self.assertEqual(l_plombier.depense_id, facture)
        self.assertEqual(releve.nombre_a_pointer, 3)
        # Réimporter ne crée pas de doublon
        releve.action_importer()
        self.assertEqual(len(releve.ligne_ids), 4)
        with self.assertRaises(UserError):
            releve.action_marquer_rapproche()

        l_bob.action_creer_reglement()
        self.assertEqual(l_bob.etat, "pointe")
        self.assertAlmostEqual(self.copro.situation_debiteur(self.bob, date(2026, 4, 30))["solde"]
                               + 500.0, self.copro.situation_debiteur(self.bob, date(2026, 4, 7))["solde"])
        l_plombier.action_creer_paiement()
        self.env.invalidate_all()
        self.assertTrue(facture.est_payee)
        self.assertEqual(l_plombier.etat, "pointe")

        # Frais bancaires non saisis : l'état de rapprochement les fait apparaître
        donnees = releve._donnees_etat()
        self.assertEqual(donnees["releve_non_pointees"], l_frais)
        self.assertAlmostEqual(donnees["ecart"], 0.0)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_gestion_courante.report_etat_rapprochement", releve.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("ÉTAT DE RAPPROCHEMENT BANCAIRE", "FRAIS TENUE DE COMPTE", "Résidence Gestion Courante"):
            self.assertIn(texte, html)
        l_frais.action_ignorer()
        releve.action_marquer_rapproche()
        self.assertEqual(releve.etat, "rapproche")
        # Dépointage
        releve.action_rouvrir()
        l_alice.action_depointer()
        self.assertFalse(l_alice.move_line_id)
        self.assertEqual(l_alice.etat, "a_pointer")

    def test_ecriture_non_passee_en_banque(self):
        # Un chèque émis le 28/04 non encore débité apparaît dans l'état
        facture = self._piece(90.0, "F-PL-2")
        facture.action_valider()
        paiement = self.env["coproerp.depense.paiement"].create({
            "depense_id": facture.id, "date": date(2026, 4, 28), "montant": 90.0, "mode": "cheque"})
        paiement.action_valider()
        releve = self._releve(OFX, "releve.ofx")
        releve.action_importer()
        self.assertAlmostEqual(releve.solde_final, 1187.5)
        self.assertEqual(releve.ligne_ids.filtered(lambda l: l.montant == 1200.0).personne_id, self.alice)
        donnees = releve._donnees_etat()
        cheque = donnees["compta_non_pointees"].filtered(lambda m: m.move_id == paiement.move_id)
        self.assertAlmostEqual(cheque.balance, -90.0)
