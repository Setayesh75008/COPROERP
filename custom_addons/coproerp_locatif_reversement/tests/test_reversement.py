"""Gestion locative, étape 3 : honoraires, factures payées pour le compte, comptes rendus, virements.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_locatif_reversement \
        --test-tags /coproerp_locatif_reversement --stop-after-init
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_locatif_reversement")
class TestReversement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.dossier = env["coproerp.locatif.dossier"].search([], limit=1) or env["coproerp.locatif.dossier"].create({
            "banque_iban": "FR7630001007941234567890185"})
        if not cls.dossier.company_id:
            cls.dossier.action_creer_dossier_comptable()
        cls.proprio = env["res.partner"].create({"name": "LEROY Hélène", "street": "3 rue Cler", "zip": "75007",
                                                 "city": "Paris"})
        cls.locataire = env["res.partner"].create({"name": "MOREL Antoine"})
        cls.plombier = env["res.partner"].create({"name": "Plomberie du Parc"})
        cls.fisc = env["res.partner"].create({"name": "Service des impôts fonciers"})
        cls.mandat = env["coproerp.locatif.mandat"].create({
            "proprietaire_id": cls.proprio.id, "date_signature": date(2024, 1, 1), "date_effet": date(2024, 1, 1),
            "taux_honoraires": 7.0, "iban_proprietaire": "FR7612345987650123456789014"})
        cls.mandat.action_activer()
        cls.bien = env["coproerp.locatif.bien"].create({
            "name": "Appartement 2e gauche", "mandat_id": cls.mandat.id, "street": "12 avenue Bosquet",
            "zip": "75007", "city": "Paris"})
        cls.bail = env["coproerp.locatif.bail"].create({
            "bien_id": cls.bien.id, "locataire_id": cls.locataire.id, "date_debut": date(2025, 3, 1),
            "loyer_hc": 1000.0, "charges": 100.0, "depot_garantie": 1000.0})
        cls.bail.action_activer()
        Echeance = env["coproerp.locatif.echeance"]
        cls.avis_mars = Echeance.creer_loyer(cls.bail, date(2025, 3, 1), date(2025, 3, 31), date(2025, 3, 1))
        # Dépôt de garantie (1 000) et loyer de mars (1 100) payés le 5 mars
        cls.encaissement = env["coproerp.locatif.encaissement"].create({
            "bail_id": cls.bail.id, "date": date(2025, 3, 5), "montant": 2100.0})
        cls.encaissement.action_valider()

    def _crg(self, debut=date(2025, 3, 1), fin=date(2025, 3, 31)):
        return self.env["coproerp.locatif.compte_rendu"].create({
            "mandat_id": self.mandat.id, "date_debut": debut, "date_fin": fin})

    def _solde(self, cle="proprietaires", partner=None):
        return self.env["coproerp.locatif.mandat"].solde_compte(
            self.proprio if partner is None and cle == "proprietaires" else partner, cle)

    def _html(self, report, ids, data=None):
        html = self.env["ir.actions.report"]._render_qweb_html(report, ids, data=data)[0]
        return html.decode() if isinstance(html, bytes) else html

    # ---------------------------------------------------------------
    def test_honoraires_et_compte_rendu(self):
        self.assertEqual(self.avis_mars.etat, "payee")
        self.assertAlmostEqual(self._solde(), 1100.0)  # le dépôt est conservé au compte 165
        crg = self._crg()
        crg.action_valider()
        self.assertAlmostEqual(crg.base_honoraires, 1100.0)  # dépôt de garantie exclu
        self.assertAlmostEqual(crg.honoraires, 77.0)
        self.assertEqual(crg.move_honoraires_id.locatif_nature, "honoraires")
        self.assertAlmostEqual(self._solde(), 1023.0)
        self.assertAlmostEqual(self._solde("honoraires", None), 77.0)
        self.assertAlmostEqual(crg.solde_debut, 0.0)
        self.assertAlmostEqual(crg.total_quittancement, 1100.0)
        self.assertAlmostEqual(crg.total_honoraires, -77.0)
        self.assertAlmostEqual(crg.solde_fin, 1023.0)
        self.assertAlmostEqual(crg.disponible, 1023.0)
        self.assertAlmostEqual(self.mandat.disponible, 1023.0)
        situation = crg.situation_baux()[0]
        self.assertEqual((situation["appele"], situation["encaisse"], situation["reste"]), (1100.0, 1100.0, 0.0))
        html = self._html("coproerp_locatif_reversement.report_compte_rendu", crg.ids)
        self.assertIn("COMPTE RENDU DE GESTION", html)
        self.assertIn("1 023,00", html)
        # Une seconde période qui chevauche serait facturée deux fois
        with self.assertRaises(ValidationError):
            self._crg(date(2025, 3, 15), date(2025, 4, 15)).action_valider()
        # Annulation : les honoraires sont rendus au propriétaire
        crg.action_annuler()
        self.assertAlmostEqual(self._solde(), 1100.0)

    def test_virement_limite_aux_fonds_encaisses(self):
        self._crg().action_valider()
        # Avril appelé mais pas payé : il est au crédit du propriétaire mais ne peut pas lui être viré
        self.env["coproerp.locatif.echeance"].creer_loyer(self.bail, date(2025, 4, 1), date(2025, 4, 30),
                                                          date(2025, 4, 1))
        situation = self.env["coproerp.locatif.mandat"].situation_proprietaire(self.proprio)
        self.assertAlmostEqual(situation["solde"], 2123.0)
        self.assertAlmostEqual(situation["impayes"], 1100.0)
        self.assertAlmostEqual(situation["disponible"], 1023.0)
        Reversement = self.env["coproerp.locatif.reversement"]
        trop = Reversement.create({"mandat_id": self.mandat.id, "montant": 2000.0, "date": date(2025, 4, 2)})
        self.assertEqual(trop.iban, "FR7612345987650123456789014")
        with self.assertRaises(UserError):
            trop.action_valider()
        virement = Reversement.create({"mandat_id": self.mandat.id, "montant": 1023.0, "date": date(2025, 4, 2)})
        virement.action_valider()
        self.assertEqual(virement.etat, "valide")
        self.assertAlmostEqual(self._solde(), 1100.0)  # il reste le loyer d'avril, non encaissé
        self.assertAlmostEqual(self.env["coproerp.locatif.mandat"].situation_proprietaire(self.proprio)["disponible"], 0.0)
        virement.action_annuler()
        self.assertAlmostEqual(self._solde(), 2123.0)

    def test_reserve_conservee(self):
        self.mandat.reserve = 300.0
        situation = self.env["coproerp.locatif.mandat"].situation_proprietaire(self.proprio)
        self.assertAlmostEqual(situation["disponible"], 800.0)
        self.assertAlmostEqual(situation["utilisable"], 1100.0)

    def test_facture_payee_pour_le_compte(self):
        Depense = self.env["coproerp.locatif.depense"]
        facture = Depense.create({"mandat_id": self.mandat.id, "bien_id": self.bien.id, "fournisseur_id": self.plombier.id,
                                  "categorie": "travaux", "libelle": "Remplacement du chauffe-eau",
                                  "date_facture": date(2025, 3, 10), "montant": 300.0})
        facture.action_payer(date(2025, 3, 12))
        self.assertEqual(facture.etat, "payee")
        self.assertAlmostEqual(self._solde(), 800.0)
        # Le fournisseur est soldé et lettré
        self.assertAlmostEqual(self._solde("fournisseurs", self.plombier), 0.0)
        self.assertTrue(all(facture.move_id.line_ids.filtered(
            lambda l: l.account_id == self.dossier.compte("fournisseurs")).mapped("reconciled")))
        # Le propriétaire n'a pas les fonds : on n'avance pas l'argent des autres mandants
        grosse = Depense.create({"mandat_id": self.mandat.id, "fournisseur_id": self.plombier.id, "categorie": "travaux",
                                 "libelle": "Réfection de la salle de bains", "montant": 5000.0})
        with self.assertRaises(UserError):
            grosse.action_payer()
        facture.action_annuler()
        self.assertEqual(facture.etat, "annulee")
        self.assertAlmostEqual(self._solde(), 1100.0)

    def test_preparation_des_comptes_rendus(self):
        autre_proprio = self.env["res.partner"].create({"name": "ROUX Bernard"})
        trimestriel = self.env["coproerp.locatif.mandat"].create({
            "proprietaire_id": autre_proprio.id, "date_signature": date(2024, 1, 1), "date_effet": date(2024, 1, 1),
            "reversement": "trimestriel"})
        trimestriel.action_activer()
        assistant = self.env["coproerp.locatif.preparation.crg"].create({
            "date_fin": date(2025, 4, 30), "mandat_ids": [(6, 0, (self.mandat | trimestriel).ids)]})
        action = assistant.action_preparer()
        crgs = self.env["coproerp.locatif.compte_rendu"].search(action["domain"])
        self.assertEqual(crgs.mandat_id, self.mandat)  # le trimestriel attend la fin juin
        self.assertEqual(crgs.etat, "valide")
        self.assertEqual(crgs.date_debut, date(2024, 1, 1))
        self.assertAlmostEqual(crgs.honoraires, 77.0)
        self.assertEqual(len(crgs.reversement_ids), 1)
        self.assertAlmostEqual(crgs.reversement_ids.montant, 1023.0)
        self.assertEqual(crgs.reversement_ids.etat, "brouillon")
        # Le compte rendu suivant repart du lendemain
        self.assertEqual(self.env["coproerp.locatif.compte_rendu"].debut_suivant(self.mandat), date(2025, 5, 1))

    def test_virement_des_honoraires_au_cabinet(self):
        self._crg().action_valider()
        action = self.env["coproerp.locatif.reversement"].action_preparer_honoraires()
        virement = self.env["coproerp.locatif.reversement"].browse(action["res_id"])
        self.assertAlmostEqual(virement.montant, 77.0)
        virement.action_valider()
        self.assertAlmostEqual(self._solde("honoraires", None), 0.0)
        self.assertAlmostEqual(self._solde(), 1023.0)  # le propriétaire n'est pas touché
        with self.assertRaises(UserError):
            self.env["coproerp.locatif.reversement"].action_preparer_honoraires()

    def test_recapitulatif_revenus_fonciers(self):
        self._crg().action_valider()
        self.env["coproerp.locatif.depense"].create({
            "mandat_id": self.mandat.id, "fournisseur_id": self.fisc.id, "categorie": "taxe_fonciere",
            "libelle": "Taxe foncière 2025", "montant": 300.0}).action_payer(date(2025, 10, 15))
        Rapport = self.env["report.coproerp_locatif_reversement.report_recap_fiscal"]
        recap = Rapport.recap(self.proprio, 2025)
        self.assertAlmostEqual(recap["totaux"]["loyers"], 1000.0)
        self.assertAlmostEqual(recap["totaux"]["charges"], 100.0)
        self.assertAlmostEqual(recap["totaux"]["depot"], 1000.0)
        self.assertAlmostEqual(recap["totaux"]["avances"], 0.0)
        self.assertAlmostEqual(recap["honoraires"], 77.0)
        self.assertEqual([(d["cle"], d["montant"]) for d in recap["depenses"]], [("taxe_fonciere", 300.0)])
        self.assertEqual(recap["nombre_locaux"], 1)
        self.assertEqual(Rapport.recap(self.proprio, 2024)["totaux"]["loyers"], 0.0)
        html = self._html("coproerp_locatif_reversement.report_recap_fiscal", self.proprio.ids, data={"annee": 2025})
        self.assertIn("REVENUS FONCIERS 2025", html)
        self.assertIn("1 000,00", html)
        # L'assistant imprime pour les propriétaires choisis
        assistant = self.env["coproerp.locatif.recap.fiscal"].create({"annee": 2025,
                                                                      "proprietaire_ids": [(6, 0, self.proprio.ids)]})
        self.assertEqual(assistant.action_imprimer()["type"], "ir.actions.report")
