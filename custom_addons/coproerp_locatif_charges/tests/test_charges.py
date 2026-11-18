"""Gestion locative, étape 2 : révision des loyers et régularisation des charges.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_locatif_charges \
        --test-tags /coproerp_locatif_charges --stop-after-init
"""

from datetime import date

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_locatif_charges")
class TestRevisionCharges(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.dossier = env["coproerp.locatif.dossier"].search([], limit=1) or env["coproerp.locatif.dossier"].create({
            "banque_iban": "FR7630001007941234567890185"})
        if not cls.dossier.company_id:
            cls.dossier.action_creer_dossier_comptable()
        cls.proprio = env["res.partner"].create({"name": "GARNIER Louise"})
        cls.locataire = env["res.partner"].create({"name": "FAURE Thomas"})
        cls.mandat = env["coproerp.locatif.mandat"].create({
            "proprietaire_id": cls.proprio.id, "date_signature": date(2024, 1, 1), "date_effet": date(2024, 1, 1)})
        cls.mandat.action_activer()

    def _bien(self, nom, **vals):
        return self.env["coproerp.locatif.bien"].create({
            "name": nom, "mandat_id": self.mandat.id, "street": "5 rue des Tilleuls", "zip": "75017",
            "city": "Paris", **vals})

    def _bail(self, **vals):
        donnees = {"bien_id": self._bien("Appartement %s" % vals.get("date_debut", "")).id,
                   "locataire_id": self.locataire.id, "date_debut": date(2025, 3, 1), "loyer_hc": 1000.0,
                   "charges": 100.0, "depot_garantie": 0.0, "indice_trimestre": "4", "indice_annee": 2024}
        donnees.update(vals)
        bail = self.env["coproerp.locatif.bail"].create(donnees)
        bail.action_activer()
        return bail

    def _solde(self, cle, partner):
        compte = self.dossier.compte(cle)
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", self.dossier.company_id.id), ("account_id", "=", compte.id),
            ("partner_id", "=", partner.id), ("parent_state", "=", "posted")])
        return round(sum(lignes.mapped("balance")), 2)

    # ---------------------------------------------------------------
    def test_table_des_indices(self):
        Indice = self.env["coproerp.locatif.indice"]
        self.assertAlmostEqual(Indice.trouver("irl", 2026, "3").valeur, 148.06)
        self.assertAlmostEqual(Indice.trouver("ilc", 2025, 2).valeur, 136.81)
        self.assertAlmostEqual(Indice.trouver("ilat", 2026, 2).valeur, 138.01)
        with self.assertRaises(ValidationError):
            Indice.create({"type_indice": "irl", "annee": 2026, "trimestre": 3, "valeur": 150.0})

    def test_revision_logement_sans_retroactivite(self):
        bail = self._bail()
        self.assertEqual(bail.date_prochaine_revision, date(2026, 3, 1))
        revision = self.env["coproerp.locatif.revision"].preparer(bail)
        self.assertAlmostEqual(revision.valeur_ancienne, 144.64)
        self.assertAlmostEqual(revision.valeur_nouvelle, 145.78)
        self.assertAlmostEqual(revision.loyer_nouveau, round(1000 * 145.78 / 144.64, 2))
        # Préparer deux fois rend la même révision
        self.assertEqual(self.env["coproerp.locatif.revision"].preparer(bail), revision)
        revision.action_appliquer()
        aujourdhui = fields.Date.context_today(revision)
        self.assertEqual(revision.date_effet, max(date(2026, 3, 1), aujourdhui))
        self.assertAlmostEqual(bail.loyer_hc, 1007.88)
        self.assertEqual((bail.indice_annee, bail.date_derniere_revision), (2025, date(2026, 3, 1)))
        self.assertEqual(bail.date_prochaine_revision, date(2027, 3, 1))
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_locatif_charges.report_revision", revision.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("RÉVISION DU LOYER", "145.78", "144.64", "FAURE Thomas"):
            self.assertIn(texte, html)

    def test_revision_perdue_apres_un_an(self):
        bail = self._bail(date_debut=date(2024, 1, 15), indice_trimestre="3", indice_annee=2023)
        revision = self.env["coproerp.locatif.revision"].preparer(bail)
        self.assertEqual(revision.date_revision, date(2025, 1, 15))
        with self.assertRaises(UserError):
            revision.action_appliquer()
        revision.action_abandonner()
        self.assertEqual(revision.etat, "abandonnee")

    def test_indice_non_publie(self):
        bail = self._bail(date_debut=date(2026, 1, 1), indice_trimestre="3", indice_annee=2026)
        with self.assertRaises(UserError):
            self.env["coproerp.locatif.revision"].preparer(bail)

    def test_revision_commerciale_avec_rappel(self):
        bail = self._bail(type_bail="commercial", date_debut=date(2025, 1, 1), loyer_hc=2000.0, charges=0.0,
                          indice_trimestre="3", indice_annee=2024)
        self.assertEqual((bail.indice, bail.tva), ("ilc", True))
        bail.generer_echeances(date(2026, 3, 31))
        revision = self.env["coproerp.locatif.revision"].preparer(bail)
        self.assertAlmostEqual(revision.loyer_nouveau, 1991.0)
        revision.action_appliquer()
        self.assertEqual(revision.date_effet, date(2026, 1, 1))  # indexation contractuelle
        rappel = revision.rappel_id
        self.assertEqual(rappel.type_echeance, "revision")
        self.assertAlmostEqual(rappel.montant_total, -9.0 * 3 * 1.2)
        self.assertAlmostEqual(bail.loyer_hc, 1991.0)
        avril = bail.generer_echeances(date(2026, 4, 30))
        self.assertAlmostEqual(avril.montant_loyer, 1991.0)

    def test_regularisation_complement_puis_trop_percu(self):
        bail = self._bail(date_debut=date(2025, 1, 1), indice="aucun")
        bail.generer_echeances(date(2025, 12, 31))
        reg = self.env["coproerp.locatif.regularisation"].create({
            "bail_id": bail.id, "date_debut": date(2025, 1, 1), "date_fin": date(2025, 12, 31),
            "ligne_ids": [Command.create({"libelle": "Eau froide et chaude", "montant": 700.0}),
                          Command.create({"libelle": "Entretien des parties communes", "montant": 650.0})]})
        reg.action_calculer_provisions()
        self.assertAlmostEqual(reg.provisions, 1200.0)
        self.assertAlmostEqual(reg.solde, 150.0)
        self.assertAlmostEqual(reg.nouvelle_provision, 112.5)
        avant = self._solde("locataires", self.locataire)
        reg.action_valider()
        self.assertEqual(reg.etat, "validee")
        self.assertAlmostEqual(reg.avis_id.montant_total, 150.0)
        self.assertEqual(reg.avis_id.type_echeance, "regularisation")
        self.assertAlmostEqual(self._solde("locataires", self.locataire), avant + 150.0)
        self.assertAlmostEqual(bail.charges, 112.5)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_locatif_charges.report_regularisation", reg.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("RÉGULARISATION DES CHARGES", "Eau froide et chaude", "Complément restant dû", "six mois"):
            self.assertIn(texte, html)
        with self.assertRaises(ValidationError):
            self.env["coproerp.locatif.regularisation"].create({
                "bail_id": bail.id, "date_debut": date(2025, 6, 1), "date_fin": date(2025, 12, 31)}).action_valider()
        # Annulation, puis régularisation avec trop-perçu
        reg.action_annuler()
        self.assertEqual(reg.avis_id.etat, "annulee")
        proprio_avant = self._solde("proprietaires", self.proprio)
        reg2 = self.env["coproerp.locatif.regularisation"].create({
            "bail_id": bail.id, "date_debut": date(2025, 1, 1), "date_fin": date(2025, 12, 31),
            "appliquer_provision": False,
            "ligne_ids": [Command.create({"libelle": "Eau", "montant": 1000.0})]})
        reg2.action_valider()
        self.assertAlmostEqual(reg2.solde, -200.0)
        self.assertAlmostEqual(reg2.avis_id.montant_total, -200.0)
        self.assertAlmostEqual(self._solde("proprietaires", self.proprio), proprio_avant + 200.0)

    def test_regularisation_forfait_refusee(self):
        bail = self._bail(type_bail="habitation_meublee", mode_charges="forfait", indice="aucun")
        with self.assertRaises(ValidationError):
            self.env["coproerp.locatif.regularisation"].create({"bail_id": bail.id})

    def test_reprise_des_charges_de_la_copropriete(self):
        env = self.env
        copro = env["coproerp.copropriete"].create({"name": "Résidence Régul", "street": "1 rue R", "zip": "75017",
                                                    "city": "Paris"})
        batiment = env["coproerp.batiment"].create({"name": "A", "copropriete_id": copro.id})
        lot = env["coproerp.lot"].create({"numero": "12", "designation": "Appartement", "batiment_id": batiment.id})
        autre = env["coproerp.lot"].create({"numero": "13", "designation": "Appartement", "batiment_id": batiment.id})
        cle = env["coproerp.repartition"].create({"name": "Charges générales", "copropriete_id": copro.id,
                                                  "type_repartition": "charges_generales", "total_tantiemes": 1000})
        env["coproerp.repartition.lot"].create({"repartition_id": cle.id, "lot_id": lot.id, "tantiemes": 300})
        env["coproerp.repartition.lot"].create({"repartition_id": cle.id, "lot_id": autre.id, "tantiemes": 700})
        env["coproerp.budget.annuel"].create({
            "copropriete_id": copro.id, "exercice": 2025, "date_debut": date(2025, 1, 1),
            "date_fin": date(2025, 12, 31), "budget_previsionnel": 5000.0,
            "ligne_ids": [Command.create({"repartition_id": cle.id, "designation": "CHARGES", "montant_annuel": 5000.0})]})
        copro.action_creer_dossier_comptable()
        fournisseur = env["res.partner"].create({"name": "Entretien Service"})
        Nature = env["coproerp.nature.depense"]
        for code, montant, reference in (("615000", 1000.0, "ENT-1"), ("616000", 2000.0, "ASS-1")):
            env["coproerp.depense"].create({
                "copropriete_id": copro.id, "fournisseur_id": fournisseur.id, "reference_fournisseur": reference,
                "date_facture": date(2025, 6, 1), "date_echeance": date(2025, 6, 30),
                "ligne_ids": [Command.create({"nature_id": Nature.search([("code", "=", code)], limit=1).id,
                                              "repartition_id": cle.id, "montant": montant})],
            }).action_valider()
        bail = self._bail(date_debut=date(2025, 1, 1), indice="aucun",
                          bien_id=self._bien("Lot 12", lot_id=lot.id).id)
        reg = env["coproerp.locatif.regularisation"].create({
            "bail_id": bail.id, "date_debut": date(2025, 1, 1), "date_fin": date(2025, 12, 31)})
        reg.action_reprendre_copropriete()
        self.assertEqual(len(reg.ligne_ids), 1)  # l'assurance (616) n'est pas récupérable
        self.assertAlmostEqual(reg.ligne_ids.montant, 300.0)
        self.assertEqual(reg.ligne_ids.origine, "copropriete")
        # Reprendre une seconde fois remplace les lignes au lieu de les doubler
        reg.action_reprendre_copropriete()
        self.assertEqual(len(reg.ligne_ids), 1)
        sans_lot = self.env["coproerp.locatif.regularisation"].create({"bail_id": self._bail(indice="aucun").id})
        with self.assertRaises(UserError):
            sans_lot.action_reprendre_copropriete()
