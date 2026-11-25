"""Gestion locative, étape 4 : états des lieux, décompte de sortie, restitution du dépôt de garantie.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_locatif_sortie \
        --test-tags /coproerp_locatif_sortie --stop-after-init
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "coproerp_locatif_sortie")
class TestSortie(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.dossier = env["coproerp.locatif.dossier"].search([], limit=1) or env["coproerp.locatif.dossier"].create({
            "banque_iban": "FR7630001007941234567890185"})
        if not cls.dossier.company_id:
            cls.dossier.action_creer_dossier_comptable()
        cls.proprio = env["res.partner"].create({"name": "BLANC Odile"})
        cls.locataire = env["res.partner"].create({"name": "CARON Julie"})
        cls.mandat = env["coproerp.locatif.mandat"].create({
            "proprietaire_id": cls.proprio.id, "date_signature": date(2024, 1, 1), "date_effet": date(2024, 1, 1)})
        cls.mandat.action_activer()
        cls.bail = cls._bail(cls.mandat, "Appartement 4e droite")

    @classmethod
    def _bail(cls, mandat, nom):
        env = cls.env
        bien = env["coproerp.locatif.bien"].create({
            "name": nom, "mandat_id": mandat.id, "street": "8 rue Lepic", "zip": "75018", "city": "Paris"})
        bail = env["coproerp.locatif.bail"].create({
            "bien_id": bien.id, "locataire_id": cls.locataire.id, "date_debut": date(2025, 3, 1),
            "loyer_hc": 1000.0, "charges": 100.0, "depot_garantie": 1000.0})
        bail.action_activer()
        env["coproerp.locatif.echeance"].creer_loyer(bail, date(2025, 3, 1), date(2025, 3, 31), date(2025, 3, 1))
        cls._payer(bail, date(2025, 3, 5), 2100.0)  # dépôt + mars
        return bail

    @classmethod
    def _payer(cls, bail, jour, montant):
        enc = cls.env["coproerp.locatif.encaissement"].create({"bail_id": bail.id, "date": jour, "montant": montant})
        enc.action_valider()
        return enc

    def _avril_paye(self, bail=None):
        bail = bail or self.bail
        self.env["coproerp.locatif.echeance"].creer_loyer(bail, date(2025, 4, 1), date(2025, 4, 30), date(2025, 4, 1))
        self._payer(bail, date(2025, 4, 3), 1100.0)

    def _sortie(self, bail=None, **vals):
        donnees = {"bail_id": (bail or self.bail).id, "date_conge": date(2025, 1, 31),
                   "date_remise_cles": date(2025, 4, 30)}
        donnees.update(vals)
        return self.env["coproerp.locatif.sortie"].create(donnees)

    def _solde(self, cle, partner):
        return self.env["coproerp.locatif.mandat"].solde_compte(partner, cle)

    def _edl(self, type_edl, **vals):
        return self.env["coproerp.locatif.etat_lieux"].create({"bail_id": self.bail.id, "type_edl": type_edl, **vals})

    # ---------------------------------------------------------------
    def test_etats_des_lieux(self):
        entree = self._edl("entree", date=date(2025, 3, 1))
        with self.assertRaises(UserError):
            entree.action_signer()  # pas de pièce
        entree.action_pieces_types()
        self.assertTrue(entree.ligne_ids)
        entree.ligne_ids.write({"etat": "bon"})
        entree.action_signer()
        self.assertEqual(entree.etat, "signe")
        doublon = self._edl("entree", ligne_ids=[(0, 0, {"piece": "Séjour", "element": "Sol", "etat": "bon"})])
        with self.assertRaises(ValidationError):
            doublon.action_signer()
        sortie_edl = self._edl("sortie", date=date(2025, 4, 30))
        self.assertEqual(sortie_edl.entree_id, entree)
        sortie_edl.action_reprendre_entree()
        self.assertEqual(len(sortie_edl.ligne_ids), len(entree.ligne_ids))
        sortie_edl.action_signer()
        self.assertTrue(sortie_edl.conforme)
        decompte = self._sortie(etat_lieux_id=sortie_edl.id)
        self.assertEqual((decompte.delai_mois, decompte.date_limite), (1, date(2025, 5, 30)))
        # Une dégradation : deux mois
        sortie_edl.action_remettre_brouillon()
        sortie_edl.ligne_ids[0].etat = "mauvais"
        sortie_edl.action_signer()
        self.assertEqual(sortie_edl.nombre_degradations, 1)
        self.assertFalse(decompte.conforme)
        self.assertEqual((decompte.delai_mois, decompte.date_limite), (2, date(2025, 6, 30)))
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_locatif_sortie.report_etat_lieux", sortie_edl.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("ÉTAT DES LIEUX DE SORTIE", html)

    def test_restitution_dans_le_delai(self):
        self._avril_paye()
        decompte = self._sortie(nouvelle_adresse="12 rue de la Paix\n69002 Lyon", retenue_ids=[
            (0, 0, {"nature": "reparations", "libelle": "Remplacement de la moquette de la chambre",
                    "justificatif": "Devis Sols Services n° 1245", "montant": 250.0})])
        self.assertAlmostEqual(decompte.depot_verse, 1000.0)
        self.assertEqual(decompte.date_fin_preavis, date(2025, 4, 30))  # congé du 31 janvier, préavis de 3 mois
        decompte.action_arreter()
        self.assertEqual(self.bail.etat, "termine")
        self.assertEqual(self.bail.date_sortie, date(2025, 4, 30))
        self.assertAlmostEqual(decompte.impayes, 0.0)
        self.assertAlmostEqual(decompte.solde_final, 750.0)
        self.assertEqual(decompte.avis_retenues_id.etat, "payee")  # payé par le dépôt
        self.assertAlmostEqual(self._solde("depots", self.locataire), 0.0)
        # Les retenues reviennent au propriétaire, qui paiera les travaux
        self.assertAlmostEqual(self._solde("proprietaires", self.proprio), 2200.0 + 250.0)
        decompte.action_restituer(date(2025, 5, 20))
        self.assertEqual(decompte.etat, "restitue")
        self.assertAlmostEqual(decompte.montant_restitue, 750.0)
        self.assertAlmostEqual(decompte.majoration, 0.0)
        self.assertAlmostEqual(self.bail.solde, 0.0)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "coproerp_locatif_sortie.report_sortie", decompte.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("DÉCOMPTE DE SORTIE", html)
        self.assertIn("750,00", html)

    def test_retenue_sans_justificatif(self):
        decompte = self._sortie(retenue_ids=[(0, 0, {"libelle": "Peinture", "montant": 100.0})])
        with self.assertRaises(UserError):
            decompte.action_arreter()

    def test_majoration_pour_retard(self):
        self._avril_paye()
        decompte = self._sortie(nouvelle_adresse="3 place Bellecour, 69002 Lyon")
        decompte.action_arreter()
        self.assertEqual(decompte.date_limite, date(2025, 6, 30))  # pas d'état des lieux : deux mois
        decompte.action_restituer(date(2025, 8, 5))
        self.assertEqual(decompte.mois_retard, 2)
        self.assertAlmostEqual(decompte.majoration, 200.0)
        self.assertAlmostEqual(decompte.montant_restitue, 1200.0)
        self.assertAlmostEqual(self._solde("proprietaires", self.proprio), 2200.0 - 200.0)

    def test_pas_de_majoration_sans_nouvelle_adresse(self):
        self._avril_paye()
        decompte = self._sortie()
        decompte.action_arreter()
        decompte.action_restituer(date(2025, 8, 5))
        self.assertAlmostEqual(decompte.majoration, 0.0)
        self.assertAlmostEqual(decompte.montant_restitue, 1000.0)

    def test_impayes_imputes_sur_le_depot(self):
        # Avril est émis à la clôture du bail et n'a pas été payé
        decompte = self._sortie()
        decompte.action_arreter()
        self.assertAlmostEqual(decompte.impayes, 1100.0)
        self.assertAlmostEqual(decompte.solde_final, -100.0)  # le locataire doit encore 100 €
        decompte.action_restituer(date(2025, 5, 10))
        self.assertAlmostEqual(decompte.montant_restitue, 0.0)
        self.assertAlmostEqual(self.bail.solde, 100.0)

    def test_provision_copropriete(self):
        self._avril_paye()
        with self.assertRaises(ValidationError):
            self._sortie(immeuble_copropriete=True, reserve=300.0)
        decompte = self._sortie(immeuble_copropriete=True, reserve=200.0)
        decompte.action_arreter()
        self.assertAlmostEqual(decompte.solde_final, 800.0)
        self.assertAlmostEqual(self._solde("depots", self.locataire), 200.0)
        decompte.action_restituer(date(2025, 5, 20))
        self.assertAlmostEqual(decompte.montant_restitue, 800.0)
        self.assertFalse(decompte.reserve_soldee)
        decompte.write({"date_approbation": date(2026, 4, 15), "charges_definitives": 50.0})
        decompte.action_solder_reserve(date(2026, 5, 10))
        self.assertTrue(decompte.reserve_soldee)
        self.assertAlmostEqual(decompte.montant_restitue_reserve, 150.0)
        self.assertAlmostEqual(self._solde("depots", self.locataire), 0.0)
        self.assertAlmostEqual(self.bail.solde, 0.0)

    def test_annulation_du_decompte(self):
        self._avril_paye()
        decompte = self._sortie(retenue_ids=[(0, 0, {"libelle": "Clés non rendues", "nature": "cles",
                                                     "justificatif": "Facture serrurier n° 88", "montant": 80.0})])
        decompte.action_arreter()
        decompte.action_annuler()
        self.assertEqual(decompte.etat, "annule")
        self.assertTrue(decompte.avis_retenues_id.annulee)
        self.assertAlmostEqual(self._solde("depots", self.locataire), 1000.0)
        self.assertAlmostEqual(self.bail.solde, 0.0)
        # Un nouveau décompte peut être établi
        self._sortie().action_arreter()

    def test_depot_reverse_au_proprietaire(self):
        autre = self.env["coproerp.locatif.mandat"].create({
            "proprietaire_id": self.proprio.id, "date_signature": date(2024, 1, 1), "date_effet": date(2024, 1, 1),
            "depot_conserve": False})
        autre.action_activer()
        bail = self._bail(autre, "Studio rez-de-chaussée")
        self._avril_paye(bail)
        avant = self._solde("proprietaires", self.proprio)
        decompte = self._sortie(bail)
        decompte.action_arreter()
        self.assertAlmostEqual(self._solde("proprietaires", self.proprio), avant - 1000.0)
        decompte.action_restituer(date(2025, 5, 10))
        self.assertAlmostEqual(decompte.montant_restitue, 1000.0)
