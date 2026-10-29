"""Tests du carnet d'entretien.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_carnet_entretien \
        --test-tags /coproerp_carnet_entretien --stop-after-init
"""

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_carnet_entretien")
class TestCarnetEntretien(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.today = fields.Date.context_today(env["coproerp.contrat"])
        cls.syndic = env["res.partner"].create({"name": "Cabinet Syndic Carnet", "is_company": True})
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Carnet", "street": "12 rue C", "zip": "75008", "city": "Paris",
            "syndic_id": cls.syndic.id, "annee_construction": 1930,
        })
        cls.assureur = env["res.partner"].create({"name": "Assurances Immeuble SA"})
        cls.ascensoriste = env["res.partner"].create({"name": "Ascenseurs Service"})
        cls.entreprise = env["res.partner"].create({"name": "Ravalement Paris SARL"})
        Contrat = env["coproerp.contrat"]
        cls.assurance = Contrat.create({
            "copropriete_id": cls.copro.id, "type_contrat": "assurance", "name": "Multirisque immeuble",
            "prestataire_id": cls.assureur.id, "reference": "POL-123",
            "date_debut": date(2025, 1, 1), "date_echeance": cls.today + timedelta(days=30), "preavis_mois": 2,
        })
        cls.entretien = Contrat.create({
            "copropriete_id": cls.copro.id, "type_contrat": "entretien", "name": "Entretien de l'ascenseur",
            "equipement": "Ascenseur", "prestataire_id": cls.ascensoriste.id, "reference": "ASC-9",
            "date_echeance": cls.today + timedelta(days=365),
        })
        cls.travaux = env["coproerp.travaux"].create({
            "copropriete_id": cls.copro.id, "name": "Ravalement de la façade", "date_vote": date(2024, 5, 1),
            "date_fin_prevue": date(2025, 6, 30), "montant_vote": 50000.0, "etat": "termine",
        })
        cls.travaux_vote = env["coproerp.travaux"].create({
            "copropriete_id": cls.copro.id, "name": "Réfection de la toiture", "date_vote": date(2026, 5, 21),
            "montant_vote": 80000.0, "etat": "vote",
        })
        env["coproerp.diagnostic"].create({
            "copropriete_id": cls.copro.id, "type_diagnostic": "amiante", "date_realisation": date(2005, 3, 1),
            "conclusion": "Absence d'amiante dans les parties communes.",
        })

    def test_alertes_et_resiliation(self):
        self.assertEqual(self.assurance.date_limite_resiliation,
                         self.assurance.date_echeance - relativedelta(months=2))
        self.assertTrue(self.assurance.alerte)
        self.assertFalse(self.entretien.alerte)
        with self.assertRaises(ValidationError):
            self.entretien.write({"date_debut": self.today + timedelta(days=400)})

    def test_reprise_des_travaux_termines(self):
        self.copro.action_reprendre_travaux_termines()
        lignes = self.copro.carnet_travaux_ids
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes.travaux_id, self.travaux)
        self.assertEqual(lignes.annee, 2025)
        # Pas de doublon
        self.copro.action_reprendre_travaux_termines()
        self.assertEqual(len(self.copro.carnet_travaux_ids), 1)

    def test_donnees_et_pdf(self):
        self.copro.action_reprendre_travaux_termines()
        d = self.copro.carnet_donnees()
        self.assertEqual(d["assurances"], self.assurance)
        self.assertEqual(d["entretien"], self.entretien)
        self.assertEqual(d["travaux_votes"], self.travaux_vote)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_carnet_entretien.report_carnet", self.copro.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("CARNET D", "POL-123", "Ascenseurs Service", "Ravalement de la façade",
                      "Réfection de la toiture", "Dossier technique amiante", "Cabinet Syndic Carnet"):
            self.assertIn(texte, html)

    def test_publication_extranet(self):
        self.copro.action_publier_carnet()
        self.assertTrue(self.copro.carnet_document_id)
        self.assertEqual(self.copro.carnet_document_id.visibilite, "tous")
