"""Sinistres : délais de déclaration, lettre à l'assureur, encaissement de l'indemnité."""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from ..models.sinistre import ajouter_jours_ouvres
from .common import CoproGestionCase


@tagged("post_install", "-at_install", "coproerp_gestion_courante")
class TestSinistre(CoproGestionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.assureur = cls.env["res.partner"].create({
            "name": "Mutuelle Immeubles Assurances", "street": "1 place de l'Assurance", "zip": "75009",
            "city": "Paris"})
        cls.contrat = cls.env["coproerp.contrat"].create({
            "copropriete_id": cls.copro.id, "type_contrat": "assurance", "name": "Multirisque immeuble",
            "prestataire_id": cls.assureur.id, "reference": "MRI-778899",
            "date_debut": date(2025, 1, 1), "date_echeance": date(2026, 12, 31),
        })

    def _sinistre(self, **vals):
        return self.env["coproerp.sinistre"].create({
            "copropriete_id": self.copro.id, "nature": "degat_eaux", "date_sinistre": date(2026, 10, 2),
            "description": "Fuite sur la colonne d'eau froide, plafond du hall endommagé.",
            "contrat_id": self.contrat.id, **vals,
        })

    def test_jours_ouvres(self):
        self.assertEqual(ajouter_jours_ouvres(date(2026, 10, 2), 5), date(2026, 10, 9))  # vendredi → vendredi
        self.assertEqual(ajouter_jours_ouvres(date(2026, 10, 2), 2), date(2026, 10, 6))

    def test_delais_de_declaration(self):
        sinistre = self._sinistre()
        self.assertTrue(sinistre.name.startswith("SIN/"))
        self.assertEqual(sinistre.date_limite_declaration, date(2026, 10, 9))
        self.assertEqual(sinistre.assureur_id, self.assureur)
        vol = self._sinistre(nature="vol")
        self.assertEqual(vol.date_limite_declaration, date(2026, 10, 6))
        catnat = self._sinistre(nature="catnat", date_arrete_catnat=date(2026, 10, 15))
        self.assertEqual(catnat.date_limite_declaration, date(2026, 11, 14))
        connu_tard = self._sinistre(date_connaissance=date(2026, 10, 12))
        self.assertEqual(connu_tard.date_limite_declaration, date(2026, 10, 19))
        # Déclaration tardive signalée
        sinistre.date_declaration = date(2026, 10, 12)
        self.assertTrue(sinistre.retard)
        sinistre.date_declaration = date(2026, 10, 8)
        self.assertFalse(sinistre.retard)
        with self.assertRaises(ValidationError):
            sinistre.date_declaration = date(2026, 9, 1)

    def test_declaration_et_lettre(self):
        sinistre = self._sinistre(montant_dommages=1500.0, lot_ids=[(6, 0, self.lot1.ids)], localisation="mixte")
        action = sinistre.action_declarer()
        self.assertEqual(action["type"], "ir.actions.report")
        self.assertEqual(sinistre.etat, "declare")
        self.assertTrue(sinistre.date_declaration)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_gestion_courante.report_declaration_sinistre", sinistre.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("DÉCLARATION DE SINISTRE", "MRI-778899", "Mutuelle Immeubles Assurances", "Dégât des eaux",
                      "Fuite sur la colonne", "L. 113-2", "Cabinet Syndic Courant"):
            self.assertIn(texte, html)
        sans_contrat = self._sinistre(contrat_id=False)
        with self.assertRaises(UserError):
            sans_contrat.action_declarer()

    def test_encaissement_indemnite(self):
        sinistre = self._sinistre(montant_dommages=1500.0, franchise=300.0)
        self.assertAlmostEqual(sinistre.indemnite_attendue, 1200.0)
        sinistre.action_declarer()
        with self.assertRaises(UserError):
            sinistre.action_encaisser_indemnite()  # clé de répartition manquante
        sinistre.repartition_id = self.cle
        banque_avant = self._solde("512000")
        sinistre.action_encaisser_indemnite(date=date(2026, 10, 20))
        self.assertEqual(sinistre.etat, "indemnise")
        self.assertAlmostEqual(sinistre.indemnite_recue, 1200.0)
        self.assertEqual(sinistre.move_indemnite_id.journal_id.code, "BQ")
        self.assertAlmostEqual(self._solde("512000"), round(banque_avant + 1200.0, 2))
        credit = sinistre.move_indemnite_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.account_id.with_company(self.company).code, "713000")
        self.assertEqual(credit.coproerp_repartition_id, self.cle)
        with self.assertRaises(UserError):
            sinistre.action_encaisser_indemnite()
