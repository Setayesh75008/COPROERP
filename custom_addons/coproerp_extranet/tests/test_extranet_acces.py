"""Tests du cloisonnement de l'extranet.

Lancement (depuis le dossier d'Odoo) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_extranet \
        --test-tags /coproerp_extranet --stop-after-init

À lancer sur une base de TEST, jamais sur la base de production.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase, new_test_user


class ExtranetCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        # Même « aujourd'hui » que le module (fuseau horaire de l'utilisateur) :
        # entre minuit et 2 h à Paris, la date UTC est encore la veille.
        today = fields.Date.context_today(env["coproerp.droit"])
        cls.today = today

        # --- Deux immeubles -------------------------------------------------
        cls.copro_a = env["coproerp.copropriete"].create({"name": "Immeuble A"})
        cls.copro_b = env["coproerp.copropriete"].create({"name": "Immeuble B"})
        bat_a = env["coproerp.batiment"].create({"name": "Bât A", "copropriete_id": cls.copro_a.id})
        bat_b = env["coproerp.batiment"].create({"name": "Bât B", "copropriete_id": cls.copro_b.id})

        def lot(bat, numero):
            return env["coproerp.lot"].create(
                {"numero": numero, "designation": "Appartement %s" % numero, "batiment_id": bat.id}
            )

        cls.lot_a1, cls.lot_a2, cls.lot_a3, cls.lot_a4 = (lot(bat_a, n) for n in ("1", "2", "3", "4"))
        cls.lot_b1 = lot(bat_b, "1")

        # --- Personnes et comptes portail -----------------------------------
        def portail(login, nom):
            user = new_test_user(env, login=login, groups="base.group_portal", name=nom,
                                 email="%s@example.com" % login)
            return user, user.partner_id

        cls.u_alice, cls.alice = portail("alice", "Alice (propriétaire A)")
        cls.u_bob, cls.bob = portail("bob", "Bob (propriétaire A)")
        cls.u_carole, cls.carole = portail("carole", "Carole (propriétaire A, conseil syndical)")
        cls.u_dan, cls.dan = portail("dan", "Dan (locataire A)")
        cls.u_eve, cls.eve = portail("eve", "Eve (propriétaire B)")
        cls.u_nue, cls.nue = portail("nue", "Nue-propriétaire A")

        Droit = env["coproerp.droit"]
        cls.droit_alice = Droit.create({"personne_id": cls.alice.id, "lot_id": cls.lot_a1.id,
                                        "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.bob.id, "lot_id": cls.lot_a2.id, "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.carole.id, "lot_id": cls.lot_a3.id, "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.dan.id, "lot_id": cls.lot_a2.id, "type_droit": "locataire"})
        Droit.create({"personne_id": cls.eve.id, "lot_id": cls.lot_b1.id, "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.nue.id, "lot_id": cls.lot_a4.id, "type_droit": "nu_proprietaire",
                      "quotite": 100.0})

        cls.mandat_carole = env["coproerp.cs.mandat"].create({
            "copropriete_id": cls.copro_a.id,
            "personne_id": cls.carole.id,
            "fonction": "president",
            "date_debut": today - timedelta(days=30),
        })

        # --- Appels de fonds -------------------------------------------------
        cle = env["coproerp.repartition"].create({
            "name": "Charges générales A",
            "copropriete_id": cls.copro_a.id,
            "type_repartition": "charges_generales",
            "total_tantiemes": 1000,
        })
        for lot_rec, tantiemes in ((cls.lot_a1, 250), (cls.lot_a2, 250), (cls.lot_a3, 250), (cls.lot_a4, 250)):
            env["coproerp.repartition.lot"].create(
                {"repartition_id": cle.id, "lot_id": lot_rec.id, "tantiemes": tantiemes}
            )

        def appel(personne, lot_rec, montant):
            a = env["coproerp.appel.charge"].create({
                "personne_id": personne.id,
                "copropriete_id": cls.copro_a.id,
                "type_appel": "budget_courant",
                "date_appel": today,
                "date_echeance": today + timedelta(days=15),
            })
            groupe = env["coproerp.appel.charge.groupe"].create({"appel_id": a.id, "lot_id": lot_rec.id})
            env["coproerp.appel.charge.poste"].create({
                "groupe_id": groupe.id,
                "type_poste": "charges_generales",
                "designation": "Charges générales",
                "repartition_id": cle.id,
                "total_a_repartir": montant,
            })
            return a

        cls.appel_alice = appel(cls.alice, cls.lot_a1, 4000.0)   # 1 000 €
        cls.appel_bob = appel(cls.bob, cls.lot_a2, 8000.0)       # 2 000 €

        # --- Documents -------------------------------------------------------
        Doc = env["coproerp.extranet.document"]
        cat = env.ref("coproerp_extranet.categorie_pv_ag")
        cat_cs = env.ref("coproerp_extranet.categorie_cs_banque")
        cat_perso = env.ref("coproerp_extranet.categorie_appels_fonds")
        fichier = "JVBERi0xLjQK"  # "%PDF-1.4"

        def doc(nom, categorie, visibilite, copro, personne=False):
            return Doc.create({
                "name": nom, "categorie_id": categorie.id, "visibilite": visibilite,
                "copropriete_id": copro.id, "personne_id": personne and personne.id,
                "fichier": fichier, "nom_fichier": "doc.pdf", "publie": True,
            })

        cls.doc_pv_a = doc("PV AG 2026", cat, "tous", cls.copro_a)
        cls.doc_pv_b = doc("PV AG immeuble B", cat, "tous", cls.copro_b)
        cls.doc_cs_a = doc("Relevé bancaire", cat_cs, "conseil_syndical", cls.copro_a)
        cls.doc_alice = doc("Appel alice", cat_perso, "personnel", cls.copro_a, cls.alice)
        cls.doc_bob = doc("Appel bob", cat_perso, "personnel", cls.copro_a, cls.bob)
        cls.doc_brouillon = Doc.create({
            "name": "Brouillon", "categorie_id": cat.id, "visibilite": "tous",
            "copropriete_id": cls.copro_a.id, "fichier": fichier, "publie": False,
        })


@tagged("post_install", "-at_install", "coproerp_extranet")
class TestExtranetAcces(ExtranetCommon):

    def _visibles(self, user, model):
        return self.env[model].with_user(user).search([])

    # ---- Copropriétés ------------------------------------------------------
    def test_coproprietes_visibles(self):
        self.assertEqual(self._visibles(self.u_alice, "coproerp.copropriete"), self.copro_a)
        self.assertEqual(self._visibles(self.u_eve, "coproerp.copropriete"), self.copro_b)
        self.assertEqual(self._visibles(self.u_nue, "coproerp.copropriete"), self.copro_a,
                         "Le nu-propriétaire doit avoir accès")

    def test_locataire_sans_acces(self):
        self.assertFalse(self._visibles(self.u_dan, "coproerp.copropriete"))
        self.assertFalse(self._visibles(self.u_dan, "coproerp.extranet.document"))
        self.assertFalse(self._visibles(self.u_dan, "coproerp.appel.charge"))

    def test_lecture_directe_interdite(self):
        """Même en connaissant l'identifiant (URL modifiée), la base refuse."""
        with self.assertRaises(AccessError):
            self.copro_b.with_user(self.u_alice).check_access("read")
        with self.assertRaises(AccessError):
            self.appel_bob.with_user(self.u_alice).check_access("read")
        with self.assertRaises(AccessError):
            self.doc_cs_a.with_user(self.u_alice).check_access("read")

    def test_ecriture_interdite(self):
        with self.assertRaises(AccessError):
            self.appel_alice.with_user(self.u_alice).write({"note": "modif"})
        with self.assertRaises(AccessError):
            self.lot_a1.with_user(self.u_alice).write({"designation": "modif"})

    # ---- Appels de fonds / comptes ----------------------------------------
    def test_appels_proprietaire(self):
        self.assertEqual(self._visibles(self.u_alice, "coproerp.appel.charge"), self.appel_alice)
        self.assertEqual(self._visibles(self.u_bob, "coproerp.appel.charge"), self.appel_bob)
        self.assertFalse(self._visibles(self.u_eve, "coproerp.appel.charge"))

    def test_appels_conseil_syndical(self):
        visibles = self._visibles(self.u_carole, "coproerp.appel.charge")
        self.assertEqual(visibles, self.appel_alice | self.appel_bob)

    def test_solde_par_coproprietaire(self):
        copro = self.copro_a.with_user(self.u_carole)
        soldes = {l["id"]: l["solde"] for l in copro._extranet_soldes_coproprietaires()}
        self.assertAlmostEqual(soldes[self.alice.id], 1000.0)
        self.assertAlmostEqual(soldes[self.bob.id], 2000.0)

    def test_situation_personnelle(self):
        ecritures = self.copro_a.with_user(self.u_alice)._extranet_ecritures(self.alice.ids)
        self.assertEqual(len(ecritures), 1)
        self.assertAlmostEqual(ecritures[-1]["solde"], 1000.0)
        # Alice ne peut pas obtenir la situation de Bob, même en la demandant
        ecritures_bob = self.copro_a.with_user(self.u_alice)._extranet_ecritures(self.bob.ids)
        self.assertEqual(ecritures_bob, [])

    def test_fin_de_mandat(self):
        self.mandat_carole.date_fin = self.today - timedelta(days=1)
        self.assertFalse(self.mandat_carole.en_cours)
        visibles = self._visibles(self.u_carole, "coproerp.appel.charge")
        self.assertFalse(visibles, "Carole n'a plus de mandat : elle ne voit plus les comptes")

    def test_vente_du_lot(self):
        self.droit_alice.date_fin = self.today - timedelta(days=1)
        self.assertFalse(self.droit_alice.acces_extranet)
        self.assertFalse(self._visibles(self.u_alice, "coproerp.copropriete"))

    def test_droit_futur_puis_cron(self):
        droit = self.env["coproerp.droit"].create({
            "personne_id": self.eve.id, "lot_id": self.lot_a4.id,
            "type_droit": "usufruitier", "date_debut": self.today + timedelta(days=1),
        })
        self.assertFalse(droit.acces_extranet)
        droit.date_debut = self.today
        self.assertTrue(droit.acces_extranet)
        self.assertEqual(self._visibles(self.u_eve, "coproerp.copropriete"), self.copro_a | self.copro_b)

    # ---- Documents -----------------------------------------------------------
    def test_documents_proprietaire(self):
        self.assertEqual(
            self._visibles(self.u_alice, "coproerp.extranet.document"),
            self.doc_pv_a | self.doc_alice,
        )

    def test_documents_conseil_syndical(self):
        self.assertEqual(
            self._visibles(self.u_carole, "coproerp.extranet.document"),
            self.doc_pv_a | self.doc_cs_a,
        )

    def test_documents_autre_immeuble(self):
        self.assertEqual(self._visibles(self.u_eve, "coproerp.extranet.document"), self.doc_pv_b)

    def test_extranet_desactive(self):
        self.copro_a.extranet_actif = False
        self.assertFalse(self._visibles(self.u_alice, "coproerp.copropriete"))
        self.assertEqual(self._visibles(self.u_alice, "coproerp.extranet.document"), self.doc_alice)

    # ---- Dématérialisation --------------------------------------------------
    def test_journal_consentement_non_modifiable(self):
        ligne = self.env["coproerp.demat.consentement"].create({
            "personne_id": self.alice.id, "type_envoi": "convocation_ag", "accord": True,
        })
        with self.assertRaises(Exception):
            ligne.write({"accord": False})
        etat = self.env["coproerp.demat.consentement"].etat_actuel(self.alice)
        self.assertTrue(etat["convocation_ag"][0])


@tagged("post_install", "-at_install", "coproerp_extranet")
class TestExtranetPages(HttpCase, ExtranetCommon):

    def test_pages_proprietaire(self):
        self.authenticate("alice", "alice")
        for url in ("/extranet", "/extranet/lots", "/extranet/situation", "/extranet/documents",
                    "/extranet/dematerialisation", "/extranet/actualites", "/extranet/reglement",
                    "/extranet/compte"):
            reponse = self.url_open(url)
            self.assertEqual(reponse.status_code, 200, url)
        self.assertIn("PV AG 2026", self.url_open("/extranet/documents").text)
        self.assertNotIn("Relevé bancaire", self.url_open("/extranet/documents").text)

    def test_page_conseil_refusee_au_proprietaire(self):
        self.authenticate("alice", "alice")
        reponse = self.url_open("/extranet/situation/coproprietaires", allow_redirects=False)
        self.assertIn(reponse.status_code, (302, 303))
        reponse = self.url_open("/extranet/situation/coproprietaire/%s" % self.bob.id,
                                allow_redirects=False)
        self.assertIn(reponse.status_code, (302, 303))
        reponse = self.url_open("/extranet/documents/%s/telecharger" % self.doc_bob.id)
        self.assertEqual(reponse.status_code, 404)

    def test_page_conseil_membre(self):
        self.authenticate("carole", "carole")
        reponse = self.url_open("/extranet/situation/coproprietaires")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("Bob", reponse.text)
        export = self.url_open("/extranet/situation/coproprietaires?export=xlsx")
        self.assertEqual(export.status_code, 200)
        self.assertIn("spreadsheetml", export.headers.get("Content-Type", ""))

    def test_telechargement_marque_lu(self):
        self.authenticate("alice", "alice")
        reponse = self.url_open("/extranet/documents/%s/telecharger" % self.doc_pv_a.id)
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(self.doc_pv_a.lecture_ids.filtered(lambda l: l.personne_id == self.alice))
