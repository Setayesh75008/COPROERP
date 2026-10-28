"""Tests de la fiche synthétique.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_fiche_synthetique \
        --test-tags /coproerp_fiche_synthetique --stop-after-init
"""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_fiche_synthetique")
class TestFicheSynthetique(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.syndic = env["res.partner"].create({
            "name": "Cabinet Syndic Fiche", "is_company": True, "street": "2 rue S", "zip": "75009", "city": "Paris"})
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Fiche", "street": "11 rue F", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185", "syndic_id": cls.syndic.id,
            "numero_rnc": "AA1234567", "annee_construction": 1965, "nombre_ascenseurs": 1,
            "type_chauffage": "collectif", "energie_chauffage": "gaz",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        cls.personnes = []
        for numero, usage, parts in (("1", "appartement", 400), ("2", "appartement", 300),
                                     ("3", "local", 200), ("4", "bureau", 100)):
            lot = env["coproerp.lot"].create({"numero": numero, "designation": usage, "usage": usage,
                                              "batiment_id": bat.id})
            personne = env["res.partner"].create({"name": "Copropriétaire %s" % numero})
            env["coproerp.droit"].create({"personne_id": personne.id, "lot_id": lot.id, "type_droit": "proprietaire"})
            env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot.id, "tantiemes": parts})
            cls.personnes.append(personne)
        cls.budget = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": 2026,
            "date_debut": date(2026, 1, 1), "date_fin": date(2026, 12, 31),
            "budget_previsionnel": 8000.0, "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 8000.0})],
        })
        cls.copro.action_creer_dossier_comptable()
        cls.budget.action_generer_appels_budget_tous()
        env["coproerp.appel.charge"].search([("budget_origine_id", "=", cls.budget.id)]).action_comptabiliser()
        # Le copropriétaire 4 (800 € appelés) a tout réglé ; les autres doivent plus de 300 €
        env["coproerp.reglement"].create({
            "copropriete_id": cls.copro.id, "personne_id": cls.personnes[3].id,
            "date": date(2026, 3, 1), "montant": 800.0}).action_valider()
        fournisseur = env["res.partner"].create({"name": "Fournisseur Fiche"})
        env["coproerp.depense"].create({
            "copropriete_id": cls.copro.id, "fournisseur_id": fournisseur.id,
            "reference_fournisseur": "FS-1", "date_facture": date(2026, 3, 1),
            "ligne_ids": [Command.create({
                "nature_id": env["coproerp.nature.depense"].search([("code", "=", "615000")]).id,
                "repartition_id": cls.cle.id, "montant": 3000.0})],
        }).action_valider()
        cls.cloture = env["coproerp.cloture"].create({"budget_id": cls.budget.id})

    def _fiche(self):
        return self.env["coproerp.fiche.synthetique"].create({"copropriete_id": self.copro.id})

    def test_donnees_reprises(self):
        fiche = self._fiche()
        self.assertEqual(fiche.cloture_id, self.cloture)
        self.assertEqual(fiche.numero_rnic, "AA1234567")
        self.assertEqual(fiche.representant, "Cabinet Syndic Fiche")
        self.assertEqual(fiche.nombre_lots, 4)
        self.assertEqual(fiche.lots_habitation, 2)
        self.assertEqual(fiche.lots_commerces, 1)
        self.assertEqual(fiche.lots_bureaux, 1)
        self.assertEqual(fiche.nombre_batiments, 1)
        self.assertEqual(fiche.periode_construction, "1961_1974")
        self.assertEqual(fiche.energie, "gaz")
        self.assertEqual(fiche.lots_principaux, 4)
        self.assertEqual(fiche.etiquettes_liste()[-1], ("Non déterminée", 1))
        self.assertAlmostEqual(fiche.charges_courantes, 3000.0)
        self.assertAlmostEqual(fiche.dettes, 3000.0)
        self.assertAlmostEqual(fiche.impayes, 7200.0)
        self.assertEqual(fiche.debiteurs_300, 3)
        # 4 lots et budget de 8 000 € : petite copropriété
        self.assertTrue(fiche.dispense_impayes)

    def test_etablissement_et_publication(self):
        fiche = self._fiche()
        with self.assertRaises(UserError):
            fiche.action_publier_extranet()
        fiche.action_etablir()
        fiche.action_publier_extranet()
        self.assertEqual(fiche.etat, "publiee")
        self.assertTrue(fiche.document_id)
        self.assertEqual(fiche.document_id.visibilite, "tous")
        with self.assertRaises(UserError):
            fiche.charges_courantes = 1.0

    def test_pdf(self):
        fiche = self._fiche()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_fiche_synthetique.report_fiche", fiche.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("FICHE SYNTHÉTIQUE DE LA COPROPRIÉTÉ", "Identification de la copropriété",
                      "Caractéristiques financières", "AA1234567", "De 1961 à 1974", "\u2612",
                      "collectif hors chauffage urbain", "3\u00a0000,00", "PROJET"):
            self.assertIn(texte, html)
        # Petite copropriété : impayés non mentionnés
        self.assertNotIn("débiteurs de plus de 300", html)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_fiche_synthetique.report_declaration_registre", fiche.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("DÉCLARATION ANNUELLE DE MISE À JOUR", html)
        self.assertIn("Ordonnance de carence", html)

    def test_attestation(self):
        import base64
        fiche = self._fiche()
        with self.assertRaises(UserError):
            fiche.action_publier_attestation()
        fiche.write({"attestation_fichier": base64.b64encode(b"%PDF-1.4 test"), "attestation_nom": "attestation.pdf"})
        fiche.action_publier_attestation()
        self.assertTrue(fiche.attestation_document_id)
