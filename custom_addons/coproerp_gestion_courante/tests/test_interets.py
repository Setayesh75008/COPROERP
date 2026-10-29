"""Intérêts au taux légal après mise en demeure.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_gestion_courante \
        --test-tags /coproerp_gestion_courante --stop-after-init
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CoproGestionCase


@tagged("post_install", "-at_install", "coproerp_gestion_courante")
class TestInterets(CoproGestionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.copro.write({"recouvrement_frais_mise_en_demeure": 40.0, "recouvrement_cle_frais_id": cls.cle.id})

    def _mise_en_demeure(self, jour):
        med = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "type_relance": "mise_en_demeure", "date": jour,
        })
        med.action_envoyer()
        return med

    def test_table_des_taux(self):
        Taux = self.env["coproerp.taux.legal"]
        self.assertAlmostEqual(Taux.periode_au(date(2026, 3, 1)).taux_autres, 2.62)
        self.assertAlmostEqual(Taux.periode_au(date(2026, 9, 1)).taux_autres, 2.75)
        self.assertAlmostEqual(Taux.periode_au(date(2026, 9, 1)).taux_particuliers, 6.84)
        with self.assertRaises(ValidationError):
            Taux.create({"date_debut": date(2026, 12, 1), "date_fin": date(2027, 5, 31),
                         "taux_particuliers": 7.0, "taux_autres": 3.0})
        with self.assertRaises(UserError):
            Taux.periode_au(date(2030, 1, 1))

    def test_interets_simples_et_reglement(self):
        med = self._mise_en_demeure(date(2026, 9, 1))
        principal = med.montant_du - 40.0
        self.assertGreater(principal, 1000.0)
        montant, detail = med.calculer_interets(date(2026, 10, 1))
        self.assertAlmostEqual(montant, round(principal * 2.75 / 100 * 30 / 365, 2))
        self.assertEqual(len(detail), 1)
        # Un règlement de 1 000 € le 16/09 réduit la base pour la seconde quinzaine
        self._reglement(self.alice, date(2026, 9, 16), 1000.0)
        montant, detail = med.calculer_interets(date(2026, 10, 1))
        attendu = principal * 2.75 / 100 * 15 / 365 + (principal - 1000.0) * 2.75 / 100 * 15 / 365
        self.assertAlmostEqual(montant, round(attendu, 2))
        self.assertEqual(len(detail), 2)
        # Taux « particuliers » si la copropriété est paramétrée ainsi
        self.copro.interets_categorie = "particuliers"
        montant, _detail = med.calculer_interets(date(2026, 10, 1))
        attendu = principal * 6.84 / 100 * 15 / 365 + (principal - 1000.0) * 6.84 / 100 * 15 / 365
        self.assertAlmostEqual(montant, round(attendu, 2))

    def test_changement_de_semestre(self):
        med = self._mise_en_demeure(date(2026, 6, 16))
        principal = med.montant_du - 40.0
        montant, detail = med.calculer_interets(date(2026, 7, 16))
        attendu = principal * (2.62 * 14 + 2.75 * 16) / 100 / 365
        self.assertAlmostEqual(montant, round(attendu, 2))
        self.assertEqual(len(detail), 2)

    def test_imputation_au_coproprietaire(self):
        med = self._mise_en_demeure(date(2026, 9, 1))
        med.interets_au = date(2026, 10, 1)
        med.action_calculer_interets()
        self.assertGreater(med.interets, 0.0)
        self.assertIn("2,75", med.interets_detail.replace(".", ","))
        avant = self._solde("450010", self.alice)
        med.action_imputer_interets()
        self.assertAlmostEqual(self._solde("450010", self.alice), round(avant + med.interets, 2))
        credit = med.move_interets_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.account_id.with_company(self.company).code, "716000")
        self.assertEqual(credit.coproerp_repartition_id, self.cle)
        with self.assertRaises(UserError):
            med.action_imputer_interets()
        # Les intérêts imputés ne sont pas pris pour un règlement
        montant, _detail = med.calculer_interets(date(2026, 10, 1))
        self.assertAlmostEqual(montant, med.interets)

    def test_pas_d_interets_sur_simple_relance(self):
        relance = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "type_relance": "relance", "date": date(2026, 9, 1)})
        relance.action_envoyer()
        with self.assertRaises(UserError):
            relance.calculer_interets(date(2026, 10, 1))
