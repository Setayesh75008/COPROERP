"""Lettre recommandée électronique AR24 (les appels à AR24 sont simulés).

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_lre \
        --test-tags /coproerp_lre --stop-after-init
"""

from datetime import date, datetime
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models import ar24
from ..models.envoi import date_ar24, nom_prenom

CHEMIN_PDF = "odoo.addons.coproerp_lre.models.origines._pdf"


@tagged("post_install", "-at_install", "coproerp_lre")
class TestLre(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.syndic = env["res.partner"].create({"name": "Cabinet Syndic LRE", "is_company": True})
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence LRE", "street": "9 rue L", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185", "syndic_id": cls.syndic.id})
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.lot = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        cls.alice = env["res.partner"].create({"name": "MARTIN Alice", "email": "alice@exemple.fr"})
        env["coproerp.droit"].create({"personne_id": cls.alice.id, "lot_id": cls.lot.id, "type_droit": "proprietaire"})
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000})
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": cls.lot.id, "tantiemes": 1000})
        budget = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": 2026,
            "date_debut": date(2026, 1, 1), "date_fin": date(2026, 12, 31), "budget_previsionnel": 4000.0,
            "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 4000.0})]})
        cls.copro.action_creer_dossier_comptable()
        budget.action_generer_appels_budget_tous()
        env["coproerp.appel.charge"].search([("budget_origine_id", "=", budget.id)]).action_comptabiliser()
        cls.compte = env["coproerp.lre.compte"].create({
            "token": "TOKEN", "cle_privee": "7X9gx9E3Qx4EiUdB63nc", "id_user": "42"})

    def setUp(self):
        super().setUp()
        self.appels = []  # appels simulés à AR24, propres à chaque test

    def _faux_ar24(self, statut_depot="waiting"):
        appels = self.appels

        def appel(compte, methode, chemin, donnees=None, fichiers=None):
            appels.append((methode, chemin, dict(donnees or {}), fichiers))
            if chemin == "attachment":
                return {"file_id": "F%d" % len(appels)}
            if methode == "POST" and chemin == "mail":
                return {"id": 777 + len(appels), "status": statut_depot, "ts_ev_date": "2026-10-30 10:00:00"}
            return {"id": donnees["id"], "status": "AR", "ts_ev_date": "2026-10-30 10:00:00",
                    "view_date": "2026-10-31 09:30:00", "proof_ar_url": "https://ar24.example/preuve-ar"}
        return patch.object(type(self.env["coproerp.lre.compte"]), "_appel", appel)

    # ---------------------------------------------------------------
    def test_chiffrement(self):
        # Exemple de la documentation AR24
        self.assertEqual(ar24.signature("2021-05-26 14:00:00", "7X9gx9E3Qx4EiUdB63nc"),
                         "bDop0cbjKpkySlpvnNGvBMg7PuYFFgPPqTTS2RAHoY0=")
        chiffre = ar24.chiffrer_reponse({"status": "SUCCESS", "result": {"id": 5}}, "2026-10-31 01:00:00", "cle")
        self.assertEqual(ar24.lire_reponse(chiffre, "2026-10-31 01:00:00", "cle")["result"]["id"], 5)
        self.assertEqual(ar24.lire_reponse('{"status": "ERROR", "message": "token"}', "d", "cle")["status"], "ERROR")
        with self.assertRaises(UserError):
            self.env["coproerp.lre.compte"]._resultat({"status": "ERROR", "message": "Token invalide"})
        with self.assertRaises(UserError):
            self.env["coproerp.lre.compte"]._resultat({"status": "maintenance"})

    def test_outils(self):
        self.assertEqual(nom_prenom("DUPONT Marie"), ("DUPONT", "Marie"))
        self.assertEqual(nom_prenom("Jean Dupont"), ("Dupont", "Jean"))
        self.assertEqual(date_ar24("2026-01-15 10:00:00"), datetime(2026, 1, 15, 9, 0))  # heure d'hiver
        self.assertFalse(date_ar24("0000-00-00 00:00:00"))

    def test_mise_en_demeure_par_lre(self):
        med = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id, "type_relance": "mise_en_demeure",
            "date": date(2026, 10, 1), "mode_envoi": "lre", "adresse_email": "alice@exemple.fr"})
        with self.assertRaises(UserError):
            med.action_envoyer_lre()  # pas encore validée
        med.action_envoyer()
        with patch(CHEMIN_PDF, return_value=b"%PDF-1.4 test"), self._faux_ar24():
            med.action_envoyer_lre()
        envoi = med.lre_envoi_id
        self.assertEqual(envoi.etat, "envoye")
        self.assertTrue(envoi.ar24_id)
        self.assertEqual((envoi.nom, envoi.prenom), ("MARTIN", "Alice"))
        mail = [a for a in self.appels if a[1] == "mail"][0][2]
        self.assertEqual((mail["to_email"], mail["eidas"], mail["dest_statut"]), ("alice@exemple.fr", "1", "particulier"))
        self.assertEqual(mail["attachment[0]"], envoi.ar24_piece_id)
        self.assertEqual(med.numero_envoi, "AR24 n° %s" % envoi.ar24_id)
        self.assertEqual(med.date_presentation, date(2026, 10, 30))
        with self.assertRaises(UserError):
            med.action_envoyer_lre()  # déjà transmise
        # Suivi : acceptation par le destinataire
        with self._faux_ar24():
            self.env["coproerp.lre.envoi"]._cron_actualiser()
        self.assertEqual(envoi.etat, "recu")
        self.assertEqual(envoi.preuve_reception_url, "https://ar24.example/preuve-ar")
        self.assertEqual(envoi.date_locale(envoi.date_reception), date(2026, 10, 31))

    def test_convocations_par_lre(self):
        ag = self.env["coproerp.ag"].create({
            "copropriete_id": self.copro.id, "date_ag": date(2027, 4, 28), "heure": 17.5, "lieu_nom": "Cabinet"})
        bob = self.env["res.partner"].create({"name": "SCI Les Tilleuls", "is_company": True})
        Convocation = self.env["coproerp.ag.convocation"]
        electronique = Convocation.create({"ag_id": ag.id, "personne_id": self.alice.id, "mode_envoi": "lre",
                                           "adresse_email": "alice@exemple.fr"})
        societe = Convocation.create({"ag_id": ag.id, "personne_id": bob.id, "mode_envoi": "lre",
                                      "adresse_email": "contact@tilleuls.fr"})
        postale = Convocation.create({"ag_id": ag.id, "personne_id": self.syndic.id, "mode_envoi": "lrar"})
        with patch(CHEMIN_PDF, return_value=b"%PDF-1.4 test"), self._faux_ar24(statut_depot="to_valid"):
            resultat = ag.action_envoyer_convocations_lre()
        self.assertIn("à valider", resultat["params"]["message"])
        self.assertEqual((electronique.etat, societe.etat, postale.etat), ("envoyee", "envoyee", "a_envoyer"))
        self.assertEqual(electronique.lre_envoi_id.etat, "a_valider")
        self.assertEqual(electronique.date_presentation, date(2026, 10, 30))
        envoi_societe = [a[2] for a in self.appels if a[1] == "mail" and a[2]["to_email"] == "contact@tilleuls.fr"][0]
        self.assertEqual((envoi_societe["dest_statut"], envoi_societe["to_company"]), ("professionnel", "SCI Les Tilleuls"))
        self.assertEqual(ag.lre_nombre, 2)
        with self.assertRaises(UserError):
            ag.action_envoyer_convocations_lre()  # plus rien à envoyer

    def test_erreur_ar24_conservee(self):
        envoi = self.env["coproerp.lre.envoi"].preparer(
            self.lot, self.copro, self.alice, "pas-une-adresse", "Test", b"%PDF", "test.pdf")
        envoi.action_envoyer()
        self.assertEqual(envoi.etat, "erreur")
        self.assertIn("invalide", envoi.erreur)

        def refus(compte, methode, chemin, donnees=None, fichiers=None):
            raise UserError("AR24 a refusé la demande : solde insuffisant")
        envoi.email = "alice@exemple.fr"
        with patch.object(type(self.env["coproerp.lre.compte"]), "_appel", refus):
            envoi.action_envoyer()
        self.assertEqual(envoi.etat, "erreur")
        self.assertIn("solde insuffisant", envoi.erreur)
