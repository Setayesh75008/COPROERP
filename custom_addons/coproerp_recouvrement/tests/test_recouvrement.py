"""Tests du recouvrement (relances, mises en demeure, frais).

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_recouvrement \
        --test-tags /coproerp_recouvrement --stop-after-init
"""

from datetime import date, timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_recouvrement")
class TestRecouvrement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.today = fields.Date.context_today(env["coproerp.relance"])
        annee = cls.today.year
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Recouvrement", "street": "6 rue R", "zip": "75008", "city": "Paris",
            "banque_iban": "FR7630001007941234567890185",
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        lot1 = env["coproerp.lot"].create({"numero": "1", "designation": "Appartement", "batiment_id": bat.id})
        lot2 = env["coproerp.lot"].create({"numero": "2", "designation": "Appartement", "batiment_id": bat.id})
        cls.alice = env["res.partner"].create({"name": "Alice Recouvrement"})
        cls.bob = env["res.partner"].create({"name": "Bob Recouvrement"})
        env["coproerp.droit"].create({"personne_id": cls.alice.id, "lot_id": lot1.id, "type_droit": "proprietaire"})
        env["coproerp.droit"].create({"personne_id": cls.bob.id, "lot_id": lot2.id, "type_droit": "proprietaire"})
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot1.id, "tantiemes": 600})
        env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot2.id, "tantiemes": 400})
        cls.budget = env["coproerp.budget.annuel"].create({
            "copropriete_id": cls.copro.id, "exercice": annee,
            "date_debut": date(annee, 1, 1), "date_fin": date(annee, 12, 31),
            "budget_previsionnel": 8000.0,
            "repartition_fonds_travaux_id": cls.cle.id,
            "ligne_ids": [(0, 0, {"repartition_id": cls.cle.id, "designation": "CHARGES GENERALES",
                                  "montant_annuel": 8000.0})],
        })
        cls.copro.action_creer_dossier_comptable()
        cls.company = cls.copro.company_id
        cls.budget.action_generer_appels_budget_tous()
        env["coproerp.appel.charge"].search([("budget_origine_id", "=", cls.budget.id)]).action_comptabiliser()
        # Bob verse largement d'avance : il n'est pas débiteur
        env["coproerp.reglement"].create({
            "copropriete_id": cls.copro.id, "personne_id": cls.bob.id,
            "date": date(annee, 1, 5), "montant": 9000.0}).action_valider()
        # Alice ne règle que 1 000 €
        env["coproerp.reglement"].create({
            "copropriete_id": cls.copro.id, "personne_id": cls.alice.id,
            "date": date(annee, 1, 10), "montant": 1000.0}).action_valider()
        cls.copro.write({
            "recouvrement_frais_mise_en_demeure": 66.0,
            "recouvrement_cle_frais_id": cls.cle.id,
        })

    def _solde(self, personne):
        return self.copro.situation_debiteur(personne, self.today)["solde"]

    def _envoyer(self, type_relance, jours=0, **vals):
        relance = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id,
            "type_relance": type_relance, "date": self.today - timedelta(days=jours), **vals,
        })
        relance.action_envoyer()
        return relance

    def _preparation(self):
        wizard = self.env["coproerp.relance.preparation"].create({"copropriete_id": self.copro.id})
        wizard.action_rechercher()
        return wizard

    # ---------------------------------------------------------------
    def test_situation_et_debiteurs(self):
        situation = self.copro.situation_debiteur(self.alice, self.today)
        self.assertGreater(situation["solde"], 0.0)
        self.assertEqual(situation["plus_ancienne"], date(self.today.year, 1, 1))
        debiteurs = self.copro.debiteurs(self.today)
        self.assertIn(self.alice, debiteurs)
        self.assertNotIn(self.bob, debiteurs)

    def test_preparation_propose_une_relance(self):
        wizard = self._preparation()
        self.assertEqual(wizard.ligne_ids.personne_id, self.alice)
        self.assertEqual(wizard.ligne_ids.proposition, "relance")
        action = wizard.action_preparer()
        relance = self.env["coproerp.relance"].search(action["domain"])
        self.assertEqual(relance.type_relance, "relance")
        self.assertEqual(relance.etat, "brouillon")
        # Un brouillon existe déjà : rien de plus n'est proposé
        self.assertEqual(self._preparation().ligne_ids.proposition, "aucune")

    def test_relance_sans_frais(self):
        solde = self._solde(self.alice)
        relance = self._envoyer("relance")
        self.assertEqual(relance.etat, "envoyee")
        self.assertTrue(relance.name.startswith("REL/"))
        self.assertEqual(relance.mode_envoi, "courrier")
        self.assertAlmostEqual(relance.montant_du, solde)
        self.assertFalse(relance.move_frais_id)
        self.assertAlmostEqual(self._solde(self.alice), solde)
        with self.assertRaises(UserError):
            relance.date = self.today - timedelta(days=3)

    def test_mise_en_demeure_apres_relance(self):
        solde = self._solde(self.alice)
        self._envoyer("relance", jours=20)
        wizard = self._preparation()
        self.assertEqual(wizard.ligne_ids.proposition, "mise_en_demeure")
        med = self._envoyer("mise_en_demeure")
        self.assertTrue(med.name.startswith("MED/"))
        self.assertEqual(med.mode_envoi, "lrar")
        self.assertAlmostEqual(med.frais, 66.0)
        self.assertAlmostEqual(med.montant_du, solde + 66.0)
        self.assertAlmostEqual(self._solde(self.alice), solde + 66.0)
        lignes = med.move_frais_id.line_ids
        credit = lignes.filtered(lambda l: l.credit)
        self.assertEqual(credit.account_id.with_company(self.company).code, "714000")
        self.assertEqual(credit.coproerp_repartition_id, self.cle)
        self.assertEqual(med.date_limite, self.today + timedelta(days=30))
        med.date_presentation = self.today
        self.assertEqual(med.date_limite, self.today + timedelta(days=30))
        self.assertFalse(med.exigibilite_anticipee)
        # Annulation : les frais sont contre-passés
        med.action_annuler()
        self.assertEqual(med.etat, "annulee")
        self.assertAlmostEqual(self._solde(self.alice), solde)

    def test_frais_sans_cle_refuses(self):
        self.copro.recouvrement_cle_frais_id = False
        relance = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id, "type_relance": "mise_en_demeure"})
        with self.assertRaises(UserError):
            relance.action_envoyer()

    def test_exigibilite_anticipee_art_19_2(self):
        med = self._envoyer("mise_en_demeure", jours=40, frais=0.0)
        self.assertTrue(med.exigibilite_anticipee)
        ligne = self._preparation().ligne_ids
        self.assertEqual(ligne.proposition, "aucune")
        self.assertIn("19-2", ligne.motif)

    def test_compte_crediteur_refuse(self):
        relance = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.bob.id, "type_relance": "relance"})
        with self.assertRaises(UserError):
            relance.action_envoyer()

    def test_relance_par_courrier_electronique(self):
        self.env["coproerp.notification.mode"].create({
            "personne_id": self.alice.id, "objet": "adresse", "email": "alice@example.com",
            "origine": "syndic"})
        relance = self._envoyer("relance")
        self.assertEqual(relance.mode_envoi, "email")
        mail = self.env["mail.mail"].search([("model", "=", "coproerp.relance"), ("res_id", "=", relance.id)])
        self.assertEqual(mail.email_to, "alice@example.com")
        self.assertTrue(mail.attachment_ids)
        med = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id, "type_relance": "mise_en_demeure"})
        self.assertEqual(med.mode_envoi, "lre")

    def test_frais_deduits_a_la_regularisation(self):
        fournisseur = self.env["res.partner"].create({"name": "Syndic Honoraires"})
        Nature = self.env["coproerp.nature.depense"]
        facture = self.env["coproerp.depense"].create({
            "copropriete_id": self.copro.id, "fournisseur_id": fournisseur.id,
            "reference_fournisseur": "H-MED", "date_facture": date(self.today.year, 3, 1),
            "ligne_ids": [
                Command.create({"nature_id": Nature.search([("code", "=", "615000")]).id,
                                "repartition_id": self.cle.id, "montant": 8000.0}),
                Command.create({"nature_id": Nature.search([("code", "=", "622000")]).id,
                                "repartition_id": self.cle.id, "montant": 66.0}),
            ],
        })
        facture.action_valider()
        self._envoyer("mise_en_demeure")
        regul = self.env["coproerp.regularisation"].create({"budget_id": self.budget.id})
        regul.action_calculer()
        # 8 066 € de factures, dont 66 € refacturés à Alice : 8 000 € à répartir
        self.assertAlmostEqual(regul.total_depenses, 8000.0)
        alice = regul.compte_ids.filtered(lambda c: c.personne_id == self.alice)
        self.assertAlmostEqual(alice.charges, 4800.0)

    def test_pdf(self):
        relance = self._envoyer("relance", jours=20)
        med = self.env["coproerp.relance"].create({
            "copropriete_id": self.copro.id, "personne_id": self.alice.id, "type_relance": "mise_en_demeure"})
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_recouvrement.report_relance", (relance | med).ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("LETTRE DE RELANCE", "MISE EN DEMEURE", "19-2", "article 36", "PROJET",
                      "INFORMATIONS POUR LE PAIEMENT", "TOTAL À PAYER", "FR7630001007941234567890185"):
            self.assertIn(texte, html)
