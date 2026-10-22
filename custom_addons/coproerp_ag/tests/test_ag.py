"""Tests de la préparation des assemblées générales.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_ag \
        --test-tags /coproerp_ag --stop-after-init
"""

from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_ag")
class TestAssembleeGenerale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence AG", "street": "7 rue A", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        Lot = env["coproerp.lot"]
        cls.lot1 = Lot.create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        cls.lot2 = Lot.create({"numero": "2", "designation": "Cave", "batiment_id": bat.id})
        cls.lot3 = Lot.create({"numero": "3", "designation": "Appartement", "batiment_id": bat.id})
        Partner = env["res.partner"]
        cls.alice = Partner.create({"name": "Alice AG", "street": "1 rue X", "zip": "75001", "city": "Paris"})
        cls.bob = Partner.create({"name": "Bob AG"})
        cls.claire = Partner.create({"name": "Claire AG"})
        Droit = env["coproerp.droit"]
        Droit.create({"personne_id": cls.alice.id, "lot_id": cls.lot1.id, "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.alice.id, "lot_id": cls.lot2.id, "type_droit": "proprietaire"})
        Droit.create({"personne_id": cls.bob.id, "lot_id": cls.lot3.id, "type_droit": "indivisaire"})
        Droit.create({"personne_id": cls.claire.id, "lot_id": cls.lot3.id, "type_droit": "indivisaire"})
        cls.lot3.mandataire_commun_id = cls.claire
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        for lot, parts in ((cls.lot1, 400), (cls.lot2, 350), (cls.lot3, 250)):
            env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot.id, "tantiemes": parts})
        cls.budget = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": 2026,
            "date_debut": date(2026, 1, 1), "date_fin": date(2026, 12, 31),
            "budget_previsionnel": 8000.0, "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 8000.0})],
        })
        cls.budget_suivant = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": 2027,
            "date_debut": date(2027, 1, 1), "date_fin": date(2027, 12, 31),
            "budget_previsionnel": 8500.0, "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 8500.0})],
        })
        cls.copro.action_creer_dossier_comptable()
        fournisseur = Partner.create({"name": "Fournisseur AG"})
        facture = env["coproerp.depense"].create({
            "copropriete_id": cls.copro.id, "fournisseur_id": fournisseur.id,
            "reference_fournisseur": "AG-1", "date_facture": date(2026, 3, 1),
            "ligne_ids": [Command.create({
                "nature_id": env["coproerp.nature.depense"].search([("code", "=", "615000")]).id,
                "repartition_id": cls.cle.id, "montant": 3000.0})],
        })
        facture.action_valider()
        cls.cloture = env["coproerp.cloture"].create({"budget_id": cls.budget.id})

    def _ag(self, **vals):
        return self.env["coproerp.ag"].create({
            "copropriete_id": self.copro.id, "date_ag": date(2027, 4, 28), "heure": 17.5,
            "lieu_nom": "Cabinet du syndic", **vals,
        })

    # ---------------------------------------------------------------
    def test_valeurs_par_defaut_et_delais(self):
        ag = self._ag()
        self.assertEqual(ag.cle_voix_id, self.cle)
        self.assertEqual(ag.total_voix, 1000)
        self.assertEqual(ag.cloture_id, self.cloture)
        self.assertEqual(ag.heure_texte(), "17h30")
        # 21 jours à compter du lendemain de la première présentation
        self.assertEqual(ag.date_limite_presentation, date(2027, 4, 6))
        # Trois jours francs (25, 26 et 27 avril) : reçu au plus tard le 24
        self.assertEqual(ag.date_limite_vpc, date(2027, 4, 24))
        self.assertEqual(ag.date_longue(), "mercredi 28 avril 2027")
        self.assertIn("AGO du 28/04/2027", ag.name)

    def test_ordre_du_jour_type(self):
        ag = self._ag()
        ag.action_ordre_du_jour_type()
        resolutions = ag.resolution_ids
        rubriques = resolutions.filtered(lambda r: r.majorite == "rubrique")
        self.assertTrue(rubriques)
        self.assertFalse(any(rubriques.mapped("numero")))
        numerotees = resolutions - rubriques
        self.assertEqual(numerotees.mapped("numero"), [str(i) for i in range(1, len(numerotees) + 1)])
        comptes = resolutions.filtered(lambda r: r.titre.startswith("Approbation des comptes"))
        self.assertEqual(len(comptes), 1)
        self.assertIn("3 000,00 €", comptes.texte)
        budget = resolutions.filtered(lambda r: "budget prévisionnel de l'exercice 2027" in r.titre)
        self.assertIn("8 500,00 €", budget.texte)
        self.assertTrue(resolutions.filtered(lambda r: r.titre == "Désignation du syndic" and r.majorite == "art25"))
        self.assertEqual(resolutions.sorted("sequence")[-1].majorite, "information")
        self.assertIn("Projet de résolutions", ag.documents_joints)
        with self.assertRaises(UserError):
            ag.action_ordre_du_jour_type()

    def test_convocations_et_voix(self):
        self.env["coproerp.notification.mode"].create({
            "personne_id": self.alice.id, "objet": "adresse", "email": "alice@example.com", "origine": "syndic"})
        ag = self._ag()
        ag.action_ordre_du_jour_type()
        ag.action_preparer_convocations()
        self.assertEqual(len(ag.convocation_ids), 2)
        alice = ag.convocation_ids.filtered(lambda c: c.personne_id == self.alice)
        claire = ag.convocation_ids.filtered(lambda c: c.personne_id == self.claire)
        self.assertEqual(alice.voix, 750)
        self.assertEqual(alice.lot_ids, self.lot1 | self.lot2)
        self.assertEqual(alice.mode_envoi, "lre")
        self.assertEqual(alice.adresse_email, "alice@example.com")
        # Indivision : convoqué en la personne du mandataire commun, voie postale à défaut d'adresse
        self.assertEqual(claire.voix, 250)
        self.assertEqual(claire.mode_envoi, "lrar")
        self.assertFalse(ag.convocation_ids.filtered(lambda c: c.personne_id == self.bob))
        # Délai de 21 jours
        alice.date_presentation = ag.date_ag - timedelta(days=22)
        self.assertTrue(alice.delai_respecte)
        alice.date_presentation = ag.date_ag - timedelta(days=21)
        self.assertFalse(alice.delai_respecte)
        # Une seconde préparation ne crée pas de doublon
        ag.action_preparer_convocations()
        self.assertEqual(len(ag.convocation_ids), 2)
        ag.action_marquer_convoquee()
        self.assertEqual(ag.etat, "convoquee")
        with self.assertRaises(UserError):
            ag.action_preparer_convocations()

    def test_indivision_sans_mandataire_commun(self):
        self.lot3.mandataire_commun_id = False
        ag = self._ag()
        ag.action_ordre_du_jour_type()
        with self.assertRaises(UserError):
            ag.action_preparer_convocations()

    def test_lignes_du_formulaire_de_vote(self):
        ag = self._ag()
        ag.write({"resolution_ids": [
            Command.create({"sequence": 1, "titre": "BUREAU", "majorite": "rubrique"}),
            Command.create({"sequence": 2, "titre": "Président de séance", "majorite": "art24"}),
            Command.create({"sequence": 3, "titre": "Désignation du syndic", "majorite": "art25"}),
            Command.create({"sequence": 4, "titre": "Travaux d'ascenseur", "majorite": "art26"}),
            Command.create({"sequence": 5, "titre": "Questions diverses", "majorite": "information"}),
        ]})
        ag.action_renumeroter()
        lignes = ag.lignes_vote()
        self.assertEqual([l.get("numero") for l in lignes], [None, "1", "2", "2 bis", "3", "3 bis", "4"])
        self.assertIn("25-1", lignes[3]["majorite"])
        self.assertFalse(lignes[-1]["vote"])
        self.assertEqual(len(ag.resolutions_votees()), 3)

    def test_documents_pdf(self):
        ag = self._ag(consultation_pieces="au cabinet, le 15 avril de 9 h à 12 h", email_vpc="ag@syndic.example")
        ag.action_ordre_du_jour_type()
        ag.action_preparer_convocations()
        Report = self.env["ir.actions.report"]
        html = Report._render_qweb_html("coproerp_ag.report_dossier_convocation", ag.convocation_ids.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("SYNDICAT DES COPROPRIÉTAIRES", "Assemblée Générale", "CONVOCATION", "PROJET DE RÉSOLUTIONS", "FORMULAIRE DE VOTE PAR CORRESPONDANCE", "POUVOIR",
                      "mercredi 28 avril 2027", "samedi 24 avril 2027", "10 %", "750", "ag@syndic.example",
                      "au cabinet, le 15 avril", "Bon pour pouvoir", "article 42-1"):
            self.assertIn(texte, html)
        html = Report._render_qweb_html("coproerp_ag.report_projet_resolutions", ag.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("RAPPEL DES MAJORITÉS", html)
        self.assertIn("Résolution n° 1", html)
