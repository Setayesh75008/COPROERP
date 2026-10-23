"""Tests de la tenue de l'assemblée (présence, votes, majorités, procès-verbal)."""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.seance import en_lettres, preambule_date


@tagged("post_install", "-at_install", "coproerp_ag")
class TestSeance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.syndic = env["res.partner"].create({"name": "Cabinet Syndic Test", "is_company": True})
        cls.copro = env["coproerp.copropriete"].create({
            "name": "Résidence Séance", "street": "8 rue S", "zip": "75008", "city": "Paris",
            "syndic_id": cls.syndic.id,
        })
        bat = env["coproerp.batiment"].create({"name": "A", "copropriete_id": cls.copro.id})
        cls.cle = env["coproerp.repartition"].create({
            "name": "Charges générales", "copropriete_id": cls.copro.id,
            "type_repartition": "charges_generales", "total_tantiemes": 1000,
        })
        cls.personnes = {}
        for numero, (nom, voix) in enumerate((("Anne", 400), ("Bruno", 300), ("Chloé", 200), ("Denis", 100)), 1):
            lot = env["coproerp.lot"].create({"numero": str(numero), "designation": "Appartement", "batiment_id": bat.id})
            partner = env["res.partner"].create({"name": nom})
            env["coproerp.droit"].create({"personne_id": partner.id, "lot_id": lot.id, "type_droit": "proprietaire"})
            env["coproerp.repartition.lot"].create({"repartition_id": cls.cle.id, "lot_id": lot.id, "tantiemes": voix})
            cls.personnes[nom] = partner
        cls.ag = env["coproerp.ag"].create({
            "copropriete_id": cls.copro.id, "date_ag": date(2027, 4, 28), "heure": 17.5,
            "type_ag": "extraordinaire", "urgence": True, "lieu_nom": "Salle de l'immeuble",
            "resolution_ids": [
                Command.create({"sequence": 1, "titre": "Président de séance", "majorite": "art24",
                                "texte": "L'assemblée désigne Anne."}),
                Command.create({"sequence": 2, "titre": "Ravalement", "majorite": "art25",
                                "texte": "L'assemblée décide le ravalement."}),
                Command.create({"sequence": 3, "titre": "Vente d'une partie commune", "majorite": "art26",
                                "texte": "L'assemblée décide la vente."}),
                Command.create({"sequence": 4, "titre": "Questions diverses", "majorite": "information"}),
            ],
        })
        cls.ag.action_renumeroter()
        cls.ag.action_preparer_convocations()
        cls.ag.action_marquer_convoquee()
        cls.ag.action_ouvrir_feuille_presence()
        cls.r1, cls.r2, cls.r3, cls.r4 = cls.ag.resolution_ids.sorted("sequence")

    def _presence(self, nom):
        return self.ag.presence_ids.filtered(lambda p: p.personne_id == self.personnes[nom])

    def _sens(self, resolution, nom, sens, tour=1):
        resolution.vote_ids.filtered(lambda v: v.tour == tour and v.personne_id == self.personnes[nom]).sens = sens

    def _seance_type(self):
        """Anne présente, Bruno représenté par Anne, Chloé par correspondance, Denis absent."""
        self._presence("Anne").statut = "present"
        self._presence("Bruno").write({"statut": "represente", "mandataire_id": self.personnes["Anne"].id})
        chloe = self._presence("Chloé")
        chloe.statut = "correspondance"
        chloe.write({"vote_correspondance_ids": [
            Command.create({"resolution_id": self.r1.id, "tour": "1", "sens": "contre"}),
            Command.create({"resolution_id": self.r2.id, "tour": "2", "sens": "pour"}),
            Command.create({"resolution_id": self.r3.id, "tour": "1", "sens": "pour"}),
        ]})

    # ---------------------------------------------------------------
    def test_nombres_en_lettres(self):
        self.assertEqual(en_lettres(2027), "deux mille vingt-sept")
        self.assertEqual(en_lettres(71), "soixante et onze")
        self.assertEqual(en_lettres(80), "quatre-vingts")
        self.assertEqual(en_lettres(91), "quatre-vingt-onze")
        self.assertEqual(en_lettres(200), "deux cents")
        self.assertEqual(en_lettres(21), "vingt et un")
        self.assertEqual(preambule_date(date(2027, 4, 1), 17.5),
                         "L'an deux mille vingt-sept, le premier avril, à dix-sept heures trente")

    def test_feuille_de_presence(self):
        self.assertEqual(len(self.ag.presence_ids), 4)
        self.assertEqual(self.ag.nombre_membres, 4)
        self.assertEqual(self.ag.total_voix_effectif, 1000)
        self._seance_type()
        self.assertEqual(self.ag.nombre_participants, 3)
        self.assertEqual(self.ag.voix_participants, 900)
        self.assertFalse(self.ag.controle_mandats)
        # Délai d'urgence : pas de contrôle des 21 jours
        self.assertTrue(all(self.ag.convocation_ids.mapped("delai_respecte")))

    def test_article_24_et_vote_par_correspondance(self):
        self._seance_type()
        self.r1.action_initialiser_vote()
        self.assertEqual(len(self.r1.vote1_ids), 3)
        self.assertEqual(self.r1.pour, 700)
        self.assertEqual(self.r1.contre, 200)
        self.assertEqual(self.r1.resultat, "adoptee")
        # Résolution amendée : un vote favorable par correspondance devient défaillant
        self.r3.amendee = True
        self.r3.action_initialiser_vote()
        chloe = self.r3.vote1_ids.filtered(lambda v: v.personne_id == self.personnes["Chloé"])
        self.assertEqual(chloe.sens, "defaillant")

    def test_article_25_passerelle(self):
        self._seance_type()
        self.r2.action_initialiser_vote()
        self._sens(self.r2, "Bruno", "contre")
        # Chloé n'a rien coché pour le premier vote : défaillante
        self.assertEqual(self.r2.pour, 400)
        self.assertEqual(self.r2.resultat, "second_vote")  # 400 < 501 mais >= 1/3 de 1000
        self.r2.action_initialiser_second_vote()
        self._sens(self.r2, "Bruno", "contre", tour=2)
        self.assertEqual(self.r2.pour2, 600)
        self.assertEqual(self.r2.contre2, 300)
        self.assertEqual(self.r2.resultat2, "adoptee")
        self.assertEqual(self.r2.decision_finale(), "adoptee")
        self.assertIn("25-1", self.r2.phrase_resultat(1))

    def test_article_25_rejet_sans_passerelle(self):
        self._seance_type()
        self.r2.action_initialiser_vote()
        self._sens(self.r2, "Anne", "contre")
        self.assertEqual(self.r2.pour, 300)
        self.assertEqual(self.r2.resultat, "rejetee")  # 300 < 1/3 de 1000
        with self.assertRaises(UserError):
            self.r2.action_initialiser_second_vote()

    def test_article_26(self):
        self._seance_type()
        self.r3.action_initialiser_vote()
        self.assertEqual(self.r3.pour, 900)
        self.assertEqual(self.r3.resultat, "adoptee")  # 3 membres sur 4, 900 >= 2/3
        self._sens(self.r3, "Anne", "contre")
        self.assertEqual(self.r3.resultat, "second_vote")  # 2 membres sur 3 votants, 500 >= 1/3
        self._sens(self.r3, "Bruno", "contre")
        self.assertEqual(self.r3.resultat, "rejetee")

    def test_controle_des_mandats(self):
        self._presence("Bruno").write({"statut": "represente", "mandataire_id": self.syndic.id})
        self.assertIn("syndic", self.ag.controle_mandats)
        mandataire = self.env["res.partner"].create({"name": "Mandataire X"})
        self._presence("Bruno").mandataire_id = mandataire
        self.assertFalse(self.ag.controle_mandats)
        # Quatre mandats représentant plus de 10 % des voix
        for nom in ("Anne", "Chloé", "Denis"):
            self._presence(nom).write({"statut": "represente", "mandataire_id": mandataire.id})
        self.assertIn("4 mandats", self.ag.controle_mandats)
        with self.assertRaises(UserError):
            self.ag.action_cloturer_seance()

    def test_vote_sans_participant_et_tous_presents(self):
        with self.assertRaises(UserError):
            self.r1.action_initialiser_vote()
        self.ag.action_tous_presents()
        self.assertEqual(set(self.ag.presence_ids.mapped("statut")), {"present"})
        self.r1.action_initialiser_vote()
        self.assertEqual(self.r1.pour, 1000)

    def test_action_saisir_votes(self):
        action = self.ag.action_saisir_votes()
        resolutions = self.env["coproerp.ag.resolution"].search(action["domain"])
        self.assertEqual(resolutions, self.r1 | self.r2 | self.r3)

    def test_reduction_des_voix_majoritaires(self):
        self._presence("Anne").voix = 700
        self.assertEqual(self._presence("Anne").voix_effectives, 600)
        self.assertEqual(self.ag.total_voix_effectif, 1200)

    def test_cloture_pv_et_notifications(self):
        self._seance_type()
        with self.assertRaises(UserError):
            self.ag.action_cloturer_seance()  # résolutions non votées
        for resolution in (self.r1, self.r3):
            resolution.action_initialiser_vote()
        self.r2.action_initialiser_vote()
        self._sens(self.r2, "Bruno", "contre")
        self.r2.action_initialiser_second_vote()
        self._sens(self.r2, "Bruno", "contre", tour=2)
        self.ag.write({"president": "Anne", "scrutateurs": "Bruno", "secretaire": "Le syndic",
                       "heure_ouverture": 17.5, "heure_cloture": 19.0})
        self.ag.action_cloturer_seance()
        self.assertEqual(self.ag.etat, "tenue")
        a_notifier = self.ag.presence_ids.filtered("pv_a_notifier")
        self.assertEqual(a_notifier.personne_id, self.personnes["Bruno"] | self.personnes["Chloé"] | self.personnes["Denis"])
        self.assertEqual(self._presence("Denis").pv_qualite, "Défaillant")
        self.assertEqual(self._presence("Bruno").pv_qualite, "Opposant")
        self._presence("Denis").pv_date_presentation = date(2027, 5, 10)
        self.assertEqual(self._presence("Denis").pv_date_limite_recours, date(2027, 7, 10))
        self.assertEqual(self.ag.date_limite_notification_pv, date(2027, 5, 28))
        Report = self.env["ir.actions.report"]
        html = Report._render_qweb_html("coproerp_ag.report_pv", self.ag.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        for texte in ("PROCÈS-VERBAL", "an deux mille vingt-sept", "ADOPTÉE", "Second vote", "BRUNO (300)",
                      "Article 42", "19h00", "en délai d"):
            self.assertIn(texte, html)
        html = Report._render_qweb_html("coproerp_ag.report_feuille_presence", self.ag.ids)[0]
        self.assertIn("FEUILLE DE PRÉSENCE", html.decode() if isinstance(html, bytes) else html)
        html = Report._render_qweb_html("coproerp_ag.report_pv_notification", self._presence("Denis").ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("NOTIFICATION DU PROCÈS-VERBAL", html)
        self.assertIn("défaillant", html)
