"""Gestion locative : baux, quittancement, encaissements, relances.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_locatif \
        --test-tags /coproerp_locatif --stop-after-init
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_locatif")
class TestGestionLocative(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.dossier = env["coproerp.locatif.dossier"].search([], limit=1) or env["coproerp.locatif.dossier"].create({
            "banque_iban": "FR7630001007941234567890185", "banque_nom": "Banque des mandants"})
        if not cls.dossier.company_id:
            cls.dossier.action_creer_dossier_comptable()
        cls.company = cls.dossier.company_id
        cls.proprio = env["res.partner"].create({"name": "LEFEBVRE Anne", "street": "3 rue du Bailleur",
                                                 "zip": "75009", "city": "Paris"})
        cls.locataire = env["res.partner"].create({"name": "MOREAU Julien", "street": "10 rue des Lilas",
                                                   "zip": "75011", "city": "Paris"})
        cls.garant = env["res.partner"].create({"name": "MOREAU Pierre", "street": "1 place du Garant",
                                                "zip": "69002", "city": "Lyon"})
        cls.mandat = env["coproerp.locatif.mandat"].create({
            "proprietaire_id": cls.proprio.id, "date_signature": date(2025, 12, 1), "date_effet": date(2025, 12, 1),
            "taux_honoraires": 7.0})
        cls.mandat.action_activer()
        cls.bien = cls._bien("Appartement T2, 3e étage")

    @classmethod
    def _bien(cls, nom, mandat=None, **vals):
        return cls.env["coproerp.locatif.bien"].create({
            "name": nom, "mandat_id": (mandat or cls.mandat).id, "street": "10 rue des Lilas", "zip": "75011",
            "city": "Paris", **vals})

    def _bail(self, **vals):
        donnees = {"bien_id": self.bien.id, "locataire_id": self.locataire.id, "date_debut": date(2026, 1, 15),
                   "loyer_hc": 900.0, "charges": 100.0, "depot_garantie": 900.0, "garant_ids": [(6, 0, self.garant.ids)]}
        donnees.update(vals)
        return self.env["coproerp.locatif.bail"].create(donnees)

    def _solde(self, cle, partner=None):
        compte = self.dossier.compte(cle)
        domaine = [("company_id", "=", self.company.id), ("account_id", "=", compte.id),
                   ("parent_state", "=", "posted")]
        if partner:
            domaine.append(("partner_id", "=", partner.id))
        return round(sum(self.env["account.move.line"].sudo().search(domaine).mapped("balance")), 2)

    def _encaisser(self, bail, montant, jour):
        enc = self.env["coproerp.locatif.encaissement"].create({
            "bail_id": bail.id, "montant": montant, "date": jour, "mode": "virement"})
        enc.action_valider()
        return enc

    # ---------------------------------------------------------------
    def test_registre_et_dossier(self):
        self.assertTrue(self.mandat.name.startswith("MG/"))
        self.assertTrue(self.proprio.role_bailleur)
        self.assertEqual(self.company.chart_template, "gerance_fr")
        self.assertEqual(self.dossier.journal("banque").default_account_id.with_company(self.company).code, "512000")
        with self.assertRaises(UserError):
            self.mandat.unlink()

    def test_regles_par_type(self):
        bail = self._bail()
        self.assertEqual((bail.duree_mois, bail.preavis_mois, bail.indice), (36, 3, "irl"))
        self.assertEqual(bail.date_fin, date(2029, 1, 14))
        self.assertAlmostEqual(bail.depot_maximum, 900.0)
        with self.assertRaises(ValidationError):
            self._bail(depot_garantie=901.0)
        with self.assertRaises(ValidationError):
            self._bail(type_bail="mobilite", depot_garantie=100.0)
        with self.assertRaises(ValidationError):
            self._bail(type_bail="habitation_meublee", depot_garantie=2700.0)
        with self.assertRaises(ValidationError):
            self._bail(duree_mois=24)
        with self.assertRaises(ValidationError):
            self._bail(type_bail="saisonnier", depot_garantie=0.0, date_fin=date(2026, 5, 1))
        with self.assertRaises(ValidationError):
            self._bail(mode_charges="forfait")
        meuble = self._bail(type_bail="habitation_meublee", depot_garantie=1800.0)
        self.assertEqual((meuble.duree_mois, meuble.preavis_mois), (12, 1))
        tendu = self._bail(bien_id=self._bien("Studio", zone_tendue=True).id)
        self.assertEqual(tendu.preavis_mois, 1)
        societe = self.env["res.partner"].create({"name": "SCI DES LILAS", "is_company": True})
        mandat_sci = self.env["coproerp.locatif.mandat"].create({"proprietaire_id": societe.id})
        mandat_sci.action_activer()
        bail_sci = self._bail(bien_id=self._bien("Appartement SCI", mandat=mandat_sci).id)
        self.assertEqual(bail_sci.duree_mois, 72)  # bailleur personne morale
        commercial = self._bail(type_bail="commercial", depot_garantie=2700.0)
        self.assertEqual((commercial.duree_mois, commercial.indice, commercial.tva), (108, "ilc", True))

    def test_quittancement_prorata_et_depot(self):
        bail = self._bail()
        bail.action_activer()
        depot = bail.echeance_ids.filtered(lambda e: e.type_echeance == "depot")
        self.assertAlmostEqual(depot.montant_total, 900.0)
        self.assertAlmostEqual(self._solde("depots", self.locataire), -900.0)  # conservé par le gestionnaire
        avis = bail.generer_echeances(date(2026, 3, 31))
        self.assertEqual(len(avis), 3)
        janvier, fevrier, mars = avis.sorted("periode_debut")
        self.assertEqual((janvier.periode_debut, janvier.periode_fin, janvier.date_echeance),
                         (date(2026, 1, 15), date(2026, 1, 31), date(2026, 1, 15)))
        self.assertAlmostEqual(janvier.montant_total, 493.55 + 54.84)
        self.assertEqual((fevrier.date_echeance, fevrier.libelle_periode()), (date(2026, 2, 1), "février 2026"))
        self.assertAlmostEqual(mars.montant_total, 1000.0)
        # Pas de doublon
        self.assertFalse(bail.generer_echeances(date(2026, 3, 31)))
        self.assertAlmostEqual(self._solde("proprietaires", self.proprio), -(548.39 + 2000.0))
        self.assertAlmostEqual(self._solde("locataires", self.locataire), 900.0 + 548.39 + 2000.0)
        self.assertAlmostEqual(bail.solde, 3448.39)

    def test_encaissements_et_quittance(self):
        bail = self._bail()
        bail.action_activer()
        bail.generer_echeances(date(2026, 3, 31))
        depot, janvier, fevrier, mars = bail.echeance_ids.sorted(lambda e: (e.date_echeance, e.id))
        self._encaisser(bail, 2448.39, date(2026, 2, 3))
        self.assertEqual((depot.etat, janvier.etat, fevrier.etat, mars.etat), ("payee", "payee", "payee", "emise"))
        partiel = self._encaisser(bail, 400.0, date(2026, 3, 5))
        self.assertEqual(mars.etat, "partielle")
        self.assertAlmostEqual(mars.montant_restant, 600.0)
        self.assertAlmostEqual(bail.solde, 600.0)
        self.assertAlmostEqual(self._solde("locataires", self.locataire), 600.0)
        banque = self.env["account.move.line"].sudo().search([
            ("company_id", "=", self.company.id), ("parent_state", "=", "posted"),
            ("account_id", "=", self.dossier.journal("banque").default_account_id.id)])
        self.assertAlmostEqual(sum(banque.mapped("balance")), 2848.39)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_locatif.report_quittance", fevrier.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("QUITTANCE DE LOYER", "février 2026", "LEFEBVRE Anne", "MOREAU Julien", "Provision sur charges"):
            self.assertIn(texte, html)
        with self.assertRaises(UserError):
            mars.action_imprimer_quittance()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_locatif.report_avis_echeance", mars.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("AVIS D", html)
        self.assertIn("Reste à payer", html)
        # Annulation d'un encaissement : l'avis redevient dû
        partiel.action_annuler()
        self.assertEqual(mars.etat, "emise")
        self.assertAlmostEqual(bail.solde, 1000.0)
        # Un avis payé ne s'annule pas
        self._encaisser(bail, 1000.0, date(2026, 3, 10))
        self.assertEqual(mars.etat, "payee")
        with self.assertRaises(UserError):
            mars.action_annuler()

    def test_avance_imputee_sur_avis_suivant(self):
        bail = self._bail(depot_garantie=0.0, date_debut=date(2026, 1, 1))
        bail.action_activer()
        bail.generer_echeances(date(2026, 1, 31))
        self._encaisser(bail, 1500.0, date(2026, 1, 2))  # 500 € d'avance
        self.assertAlmostEqual(bail.solde, -500.0)
        bail.generer_echeances(date(2026, 2, 28))
        fevrier = bail.echeance_ids.filtered(lambda e: e.periode_debut == date(2026, 2, 1))
        self.assertEqual(fevrier.etat, "partielle")
        self.assertAlmostEqual(fevrier.montant_restant, 500.0)

    def test_trimestriel_echu_et_tva(self):
        local = self._bien("Local commercial", type_bien="local_commercial")
        bail = self._bail(bien_id=local.id, type_bail="commercial", date_debut=date(2026, 1, 1), loyer_hc=2000.0,
                          charges=200.0, depot_garantie=6000.0, periodicite="trimestriel", terme="echu")
        bail.action_activer()
        avis = bail.generer_echeances(date(2026, 6, 30))
        self.assertEqual(len(avis), 2)
        t1 = avis.sorted("periode_debut")[0]
        self.assertEqual((t1.periode_debut, t1.periode_fin, t1.date_echeance),
                         (date(2026, 1, 1), date(2026, 3, 31), date(2026, 3, 31)))
        self.assertAlmostEqual(t1.montant_loyer, 6000.0)
        self.assertAlmostEqual(t1.montant_total, 6600.0 * 1.2)

    def test_sortie_et_dernier_prorata(self):
        bail = self._bail(depot_garantie=0.0, date_debut=date(2026, 1, 1))
        bail.action_activer()
        bail.date_sortie = date(2026, 4, 10)
        bail.action_terminer()
        self.assertEqual(bail.etat, "termine")
        avril = bail.echeance_ids.filtered(lambda e: e.periode_debut == date(2026, 4, 1))
        self.assertEqual(avril.periode_fin, date(2026, 4, 10))
        self.assertAlmostEqual(avril.montant_total, round(900 * 10 / 30, 2) + round(100 * 10 / 30, 2))
        self.assertFalse(bail.generer_echeances(date(2026, 12, 31)))

    def test_relances(self):
        bail = self._bail(depot_garantie=0.0, date_debut=date(2026, 1, 1))
        bail.action_activer()
        bail.generer_echeances(date(2026, 3, 31))
        self._encaisser(bail, 2000.0, date(2026, 2, 2))
        self.assertGreater(bail.jours_retard, 0)
        relance = self.env["coproerp.locatif.relance"].preparer(bail)
        self.assertEqual((relance.type_relance, relance.destinataire_id), ("relance", self.locataire))
        relance.action_envoyer()
        self.assertTrue(relance.name.startswith("RL/"))
        self.assertAlmostEqual(relance.montant_du, 1000.0)
        relance.date = date(2026, 4, 1)
        mise_en_demeure = self.env["coproerp.locatif.relance"].preparer(bail)
        self.assertEqual((mise_en_demeure.type_relance, mise_en_demeure.mode_envoi), ("mise_en_demeure", "lrar"))
        caution = self.env["coproerp.locatif.relance"].create({
            "bail_id": bail.id, "type_relance": "information_garant", "destinataire_id": self.garant.id})
        caution.action_envoyer()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_locatif.report_relance_locataire", (mise_en_demeure | caution).ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("MISE EN DEMEURE", "INFORMATION DE LA CAUTION", "MOREAU Pierre", "clause"):
            self.assertIn(texte, html)
        self._encaisser(bail, 1000.0, date(2026, 4, 5))
        with self.assertRaises(UserError):
            self.env["coproerp.locatif.relance"].preparer(bail)

    def test_bien_deja_loue(self):
        self._bail().action_activer()
        with self.assertRaises(UserError):
            self._bail().action_activer()
