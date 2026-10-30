"""Import Excel d'une copropriété.

Lancement (base de TEST uniquement) :
    python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_import \
        --test-tags /coproerp_import --stop-after-init
"""

import base64
import io
from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models import lecture
from ..models.import_excel import modele_classeur


def classeur(feuilles):
    import openpyxl

    wb = openpyxl.Workbook()
    for index, (titre, lignes) in enumerate(feuilles):
        ws = wb.active if index == 0 else wb.create_sheet()
        ws.title = titre
        for ligne in lignes:
            ws.append(ligne)
    flux = io.BytesIO()
    wb.save(flux)
    return base64.b64encode(flux.getvalue())


@tagged("post_install", "-at_install", "coproerp_import")
class TestImportExcel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.copro = cls.env["coproerp.copropriete"].create({
            "name": "Résidence Import", "street": "4 rue I", "zip": "75008", "city": "Paris"})

    def _import(self, fichier, **vals):
        return self.env["coproerp.import.excel"].create({
            "copropriete_id": self.copro.id, "fichier": fichier, "fichier_nom": "test.xlsx", **vals})

    def _lots(self):
        return self.env["coproerp.lot"].search([("copropriete_id", "=", self.copro.id)])

    def test_modele_complet(self):
        imp = self._import(base64.b64encode(modele_classeur()), sens_solde="negatif_debiteur",
                           date_reprise=date(2025, 12, 31))
        imp.action_analyser()
        self.assertEqual(imp.nombre_anomalies, 0, imp.rapport)
        self.assertIn("Lots : 2 dont 2 nouveaux", imp.rapport)
        self.assertEqual(len(self._lots()), 0)  # l'analyse ne crée rien
        imp.action_importer()
        self.assertEqual(imp.etat, "importe")
        lots = self._lots()
        self.assertEqual(sorted(lots.mapped("numero")), ["1", "101"])
        cave = lots.filtered(lambda l: l.numero == "101")
        self.assertEqual((cave.usage, cave.type_lot, cave.batiment_id.name), ("cave", "secondaire", "A"))
        dupont = self.env["res.partner"].search([("ref", "=", "61651/1")])
        self.assertEqual(dupont.name, "DUPONT Marie")
        self.assertEqual(dupont.zip, "75008")
        self.assertTrue(dupont.role_coproprietaire)
        self.assertEqual(len(lots.droit_ids), 2)
        self.assertEqual(lots.droit_ids.mapped("date_debut"), [date(2012, 3, 15)] * 2)
        self.assertEqual(lots[0]._destinataire_appels(date(2026, 1, 1))[0], dupont)
        cles = self.env["coproerp.repartition"].search([("copropriete_id", "=", self.copro.id)])
        self.assertEqual(set(cles.mapped("name")), {"Ascenseur", "Chauffage", "Charges générales"})
        generales = cles.filtered(lambda c: c.name == "Charges générales")
        self.assertEqual((generales.type_repartition, generales.total_tantiemes, generales.etat_repartition),
                         ("charges_generales", 125, "complet"))
        self.assertEqual(cles.filtered(lambda c: c.name == "Ascenseur").type_repartition, "ascenseur_escalier")
        self.assertEqual(lots.filtered(lambda l: l.numero == "1").tantiemes, 120)
        reprise = imp.reprise_id
        self.assertEqual((reprise.etat, reprise.date_reprise), ("brouillon", date(2025, 12, 31)))
        ligne = reprise.coproprietaire_ids
        self.assertEqual(ligne.personne_id, dupont)
        self.assertAlmostEqual(ligne.solde, 350.25)  # solde négatif = dû
        self.assertAlmostEqual(ligne.fonds_travaux, 840.0)
        self.assertAlmostEqual(ligne.avance, 150.0)

        # Second import du même fichier : mise à jour sans doublon
        imp2 = self._import(base64.b64encode(modele_classeur()), sens_solde="negatif_debiteur",
                            date_reprise=date(2025, 12, 31))
        imp2.action_analyser()
        self.assertIn("0 nouveaux", imp2.rapport)
        imp2.action_importer()
        self.assertEqual(len(self._lots()), 2)
        self.assertEqual(len(self.env["res.partner"].search([("ref", "=", "61651/1")])), 1)
        self.assertEqual(len(self._lots().droit_ids), 2)
        self.assertEqual(len(self.env["coproerp.repartition"].search([("copropriete_id", "=", self.copro.id)])), 3)
        self.assertEqual(imp2.reprise_id, reprise)
        self.assertEqual(len(reprise.coproprietaire_ids), 1)

    def test_anomalies_bloquantes(self):
        fichier = classeur([
            ("Lots", [["N° de lot", "Désignation"], ["1", "Appartement"], ["1", "Doublon"]]),
            ("Copropriétaires", [["N° de compte", "Nom", "Lots", "Type de droit"],
                                 ["C1", "MARTIN", "1, 7", "Propriétaire"], ["C2", "DURAND", "1", "Fermier"]]),
            ("Tantièmes", [["N° de lot", "Charges générales"], ["1", 12.5]]),
            ("Soldes", [["N° de compte", "Nom", "Solde"], ["C1", "MARTIN", 100], ["C9", "INCONNU", 50]]),
        ])
        imp = self._import(fichier)
        imp.action_analyser()
        rapport = imp.rapport
        for texte in ("Lot 1 en double", "lot 7 inconnu", "Fermier", "nombres entiers", "sens des soldes",
                      "date d'arrêté", "C9 INCONNU introuvable"):
            self.assertIn(texte, rapport)
        self.assertGreaterEqual(imp.nombre_anomalies, 7)
        imp.action_importer()
        self.assertNotEqual(imp.etat, "importe")
        self.assertFalse(self._lots())

    def test_soldes_seuls_format_ancien_syndic(self):
        # Copropriétaires déjà créés (n° de compte de l'ancien syndic dans « Référence »)
        imp = self._import(classeur([
            ("Lots", [["N° de lot", "Usage", "Tantièmes"], ["1", "Appartement", 600], ["2", "Appartement", 400]]),
            ("Copropriétaires", [["N° de compte", "Nom", "Lots"], ["61651/9", "HD", "1"], ["61651/4", "OD", "2"]]),
        ]))
        imp.action_analyser()
        imp.action_importer()
        self.assertEqual(self.env["coproerp.repartition"].search(
            [("copropriete_id", "=", self.copro.id)]).total_tantiemes, 1000)
        soldes = self._import(classeur([("Worksheet", [
            ["N° de contrat", "Nom du copropriétaire", "Solde"],
            ["61651/9", "HD", -3304.92], ["61651/4", "OD", 232.37]])]),
            sens_solde="positif_debiteur", date_reprise=date(2025, 12, 31))
        soldes.action_analyser()
        self.assertEqual(soldes.nombre_anomalies, 0, soldes.rapport)
        soldes.action_importer()
        lignes = soldes.reprise_id.coproprietaire_ids
        hd = lignes.filtered(lambda l: l.personne_id.ref == "61651/9")
        od = lignes.filtered(lambda l: l.personne_id.ref == "61651/4")
        self.assertAlmostEqual(hd.solde, -3304.92)  # positif = dû : HD est créditeur
        self.assertAlmostEqual(od.solde, 232.37)

    def test_indivision_et_mandataire(self):
        fichier = classeur([
            ("Lots", [["N° de lot", "Désignation"], ["5", "Appartement"]]),
            ("Copropriétaires", [["Nom", "Lots", "Type de droit", "Quote-part", "Mandataire commun"],
                                 ["LEROY Paul", "5", "Indivisaire", 50, "Oui"],
                                 ["LEROY Anne", "5", "Indivisaire", 50, ""]]),
        ])
        imp = self._import(fichier)
        imp.action_analyser()
        self.assertNotIn("sans mandataire commun", imp.rapport)
        imp.action_importer()
        lot = self._lots()
        self.assertEqual(lot.mandataire_commun_id.name, "LEROY Paul")
        self.assertEqual(lot._destinataire_appels()[0], lot.mandataire_commun_id)
        self.assertEqual(sorted(lot.droit_ids.mapped("quotite")), [50.0, 50.0])

    def test_lecture(self):
        self.assertEqual(lecture.liste_lots("1, 12 et 15"), ["1", "12", "15"])
        self.assertAlmostEqual(lecture.nombre_cellule("1 234,56 €"), 1234.56)
        self.assertEqual(lecture.usage_lot("Box"), "parking")
        self.assertEqual(lecture.nature_lot("", "parking"), "secondaire")
        self.assertEqual(lecture.type_droit("Usufruitier"), "usufruitier")
        self.assertEqual(lecture.type_cle("Chauffage collectif"), "chauffage")
