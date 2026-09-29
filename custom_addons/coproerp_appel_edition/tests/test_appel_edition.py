"""Tests de la génération et de l'édition des appels de fonds.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_appel_edition \
        --test-tags /coproerp_appel_edition --stop-after-init
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_appel_edition")
class TestAppelEdition(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Immeuble Test", "street": "1 rue du Test", "zip": "75008", "city": "Paris",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})

        def lot(numero, tantiemes):
            return env["coproerp.lot"].create({
                "numero": numero, "designation": "Appartement %s" % numero,
                "batiment_id": bat.id, "tantiemes": tantiemes, "etage": "2",
            })

        cls.lot1, cls.lot2, cls.lot3, cls.lot4 = lot("1", 500), lot("2", 300), lot("3", 200), lot("4", 1)
        Partner = env["res.partner"]
        cls.alice = Partner.create({"name": "Alice", "street": "3 rue X", "zip": "75001", "city": "Paris"})
        cls.bob = Partner.create({"name": "Bob"})
        cls.usufruitier = Partner.create({"name": "Usufruitier"})
        cls.nu_prop = Partner.create({"name": "Nu-propriétaire"})
        cls.mandataire = Partner.create({"name": "Mandataire commun"})
        cls.syndicat = Partner.create({"name": "SDC Immeuble Test"})

        Droit = env["coproerp.droit"]
        Droit.create({"personne_id": cls.alice.id, "lot_id": cls.lot1.id, "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.alice.id, "lot_id": cls.lot2.id, "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.usufruitier.id, "lot_id": cls.lot3.id, "type_droit": "usufruitier"})
        Droit.create({"personne_id": cls.nu_prop.id, "lot_id": cls.lot3.id, "type_droit": "nu_proprietaire"})
        Droit.create({"personne_id": cls.syndicat.id, "lot_id": cls.lot4.id, "type_droit": "proprietaire"})
        cls.lot3.mandataire_commun_id = cls.mandataire
        cls.lot4.propriete_syndicat = True

        Cle = env["coproerp.repartition"]
        cls.cle_generale = Cle.create({
            "name": "Charges communes générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        cls.cle_chauffage = Cle.create({
            "name": "Chauffage", "copropriete_id": cls.copro.id,
            "type_repartition": "chauffage", "total_tantiemes": 800,
        })
        Ligne = env["coproerp.repartition.lot"]
        for l, t in ((cls.lot1, 500), (cls.lot2, 300), (cls.lot3, 200)):
            Ligne.create({"repartition_id": cls.cle_generale.id, "lot_id": l.id, "tantiemes": t})
        for l, t in ((cls.lot1, 500), (cls.lot2, 300)):
            Ligne.create({"repartition_id": cls.cle_chauffage.id, "lot_id": l.id, "tantiemes": t})

        cls.budget = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": 2026,
            "date_debut": date(2026, 1, 1), "date_fin": date(2026, 12, 31),
            "budget_previsionnel": 10000.0,
            "repartition_fonds_travaux_id": cls.cle_generale.id,
            "ligne_ids": [
                (0, 0, {"repartition_id": cls.cle_generale.id, "designation": "CHARGES COMMUNES GENERALES",
                        "montant_annuel": 6000.0}),
                (0, 0, {"repartition_id": cls.cle_chauffage.id, "designation": "CHARGES CHAUFFAGE",
                        "montant_annuel": 4000.0}),
            ],
        })

    def _appels(self, **domaine):
        return self.env["coproerp.appel.charge"].search(
            [(k, "=", v) for k, v in domaine.items()])

    # ---------------------------------------------------------------
    def test_periodes_trimestres(self):
        periodes = self.env["coproerp.appel.charge"]._periodes(date(2026, 1, 1), 4)
        self.assertEqual([p[1] for p in periodes],
                         [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)])
        self.assertEqual(periodes[0][2], date(2026, 3, 31))
        with self.assertRaises(UserError):
            self.env["coproerp.appel.charge"]._periodes(date(2026, 1, 1), 5)

    def test_budget_courant_premiere_echeance(self):
        self.budget.action_generer_appel_budget_suivant()
        appels = self._appels(budget_origine_id=self.budget.id)
        # Alice (lots 1 et 2 regroupés) + mandataire commun (lot 3) ; lot 4 (syndicat) exclu
        self.assertEqual(appels.personne_id, self.alice | self.mandataire)
        appel_alice = appels.filtered(lambda a: a.personne_id == self.alice)
        self.assertEqual(len(appel_alice), 1)
        self.assertEqual(appel_alice.groupe_ids.lot_id, self.lot1 | self.lot2)
        self.assertEqual(appel_alice.date_echeance, date(2026, 1, 1))
        self.assertEqual(appel_alice.date_appel, date(2025, 12, 17))
        self.assertEqual(appel_alice.libelle_echeance, "1er trimestre 2026")
        # 1500 € de charges générales par trimestre : 750 + 450 ; chauffage 1000 € : 625 + 375
        self.assertAlmostEqual(appel_alice.total_appel, 750 + 450 + 625 + 375)
        appel_mandataire = appels - appel_alice
        # Lot 3 : pas de part de chauffage -> une seule ligne
        self.assertEqual(len(appel_mandataire.groupe_ids.poste_ids), 1)
        self.assertAlmostEqual(appel_mandataire.total_appel, 300.0)
        # Relancer ne duplique pas : on passe à l'échéance 2
        self.budget.action_generer_appel_budget_suivant()
        self.assertEqual(len(self._appels(budget_origine_id=self.budget.id)), 4)

    def test_mandataire_commun_obligatoire(self):
        self.lot3.mandataire_commun_id = False
        with self.assertRaises(UserError):
            self.budget.action_generer_appel_budget_suivant()
        self.assertFalse(self._appels(budget_origine_id=self.budget.id),
                         "Rien ne doit être créé si un lot n'a pas de destinataire")

    def test_ventilation_incomplete(self):
        self.budget.ligne_ids[0].montant_annuel = 5000.0
        with self.assertRaises(UserError):
            self.budget.action_generer_appel_budget_suivant()

    def test_dernier_trimestre_absorbe_arrondis(self):
        self.budget.budget_previsionnel = 10000.02
        self.budget.ligne_ids[0].montant_annuel = 6000.02
        self.budget.action_generer_appels_budget_tous()
        postes = self._appels(budget_origine_id=self.budget.id).groupe_ids.poste_ids.filtered(
            lambda p: p.repartition_id == self.cle_generale)
        par_echeance = {}
        for p in postes:
            par_echeance[p.appel_id.numero_appel_budget] = p.total_a_repartir
        self.assertAlmostEqual(sum(par_echeance.values()), 6000.02, places=2)

    def test_montants_arrondis_au_centime(self):
        cle = self.env["coproerp.repartition"].create({
            "name": "Tiers", "copropriete_id": self.copro.id,
            "type_repartition": "autre", "total_tantiemes": 3,
        })
        for l in (self.lot1, self.lot2, self.lot3):
            self.env["coproerp.repartition.lot"].create({"repartition_id": cle.id, "lot_id": l.id, "tantiemes": 1})
        self.budget.write({"budget_previsionnel": 11000.0, "ligne_ids": [
            (0, 0, {"repartition_id": cle.id, "designation": "DIVERS", "montant_annuel": 1000.0})]})
        self.budget.action_generer_appel_budget_suivant()
        postes = self._appels(budget_origine_id=self.budget.id).groupe_ids.poste_ids.filtered(
            lambda p: p.repartition_id == cle)
        for p in postes:
            self.assertEqual(round(p.montant_appel, 2), p.montant_appel)
            self.assertAlmostEqual(p.montant_appel, 83.33)

    def test_fonds_travaux_cle_generale(self):
        self.budget.action_generer_appel_fonds_suivant()
        appels = self._appels(budget_id=self.budget.id, type_appel="fonds_travaux")
        self.assertEqual(appels.personne_id, self.alice | self.mandataire)
        # 5 % de 10 000 = 500 / an, 125 par trimestre ; Alice : 80 % = 100
        alice = appels.filtered(lambda a: a.personne_id == self.alice)
        self.assertAlmostEqual(alice.total_appel, 100.0)

    def test_echeancier_travaux_et_honoraires(self):
        travaux = self.env["coproerp.travaux"].create({
            "copropriete_id": self.copro.id, "name": "Ravalement façade",
            "date_vote": date(2026, 5, 21), "montant_vote": 10000.0, "etat": "vote",
        })
        financement = self.env["coproerp.travaux.financement"].create({
            "travaux_id": travaux.id, "type_financement": "appel_exceptionnel",
            "name": "Appels ravalement", "montant_prevu": 10000.0, "nombre_appels": 3,
            "honoraires_syndic": 500.0, "repartition_id": self.cle_generale.id,
        })
        echeance = self.env["coproerp.travaux.echeance"].create({
            "financement_id": financement.id, "pourcentage": 40.0,
            "date_echeance": date(2026, 9, 15),
        })
        echeance.action_generer_appels()
        appels = echeance.appel_ids
        alice = appels.filtered(lambda a: a.personne_id == self.alice)
        # 40 % de 10 000 = 4 000 ; honoraires 40 % de 500 = 200 ; Alice 80 %
        self.assertAlmostEqual(alice.total_appel, (4000 + 200) * 0.8)
        libelles = alice.groupe_ids.poste_ids.mapped("designation")
        self.assertIn("HONORAIRES SYNDIC", libelles)
        # Une modification ultérieure ne doit pas écraser le montant de l'échéance
        poste = alice.groupe_ids.poste_ids.filtered(lambda p: p.designation != "HONORAIRES SYNDIC")[:1]
        poste.write({"sequence": 99})
        self.assertAlmostEqual(poste.total_a_repartir, 4000.0)

    def test_avis_pdf(self):
        self.budget.action_generer_appel_budget_suivant()
        self.budget.action_generer_appel_fonds_suivant()
        appels = self._appels(copropriete_id=self.copro.id).filtered(
            lambda a: a.personne_id == self.alice)
        avis = appels.avis_regroupes()
        self.assertEqual(len(avis), 1, "Budget et fonds travaux sur un seul avis")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_appel_edition.report_avis_appel", appels.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("APPEL DE FONDS", html)
        self.assertIn("BUDGET COURANT", html)
        self.assertIn("FONDS OBLIGATOIRE TRAVAUX", html)
        self.assertIn("1er trimestre 2026", html)

    def test_publication_extranet(self):
        self.budget.action_generer_appel_budget_suivant()
        appels = self._appels(budget_origine_id=self.budget.id)
        appels.action_publier_avis_extranet()
        docs = self.env["coproerp.extranet.document"].search([("appel_id", "in", appels.ids)])
        self.assertEqual(len(docs), 2)
        self.assertTrue(all(d.visibilite == "personnel" and d.publie for d in docs))
        # Une seconde publication ne crée pas de doublon
        appels.action_publier_avis_extranet()
        self.assertEqual(self.env["coproerp.extranet.document"].search_count(
            [("appel_id", "in", appels.ids)]), 2)
