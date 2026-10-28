from odoo import fields, models

PERIODES_CONSTRUCTION = [
    ("avant_1949", "Avant 1949"),
    ("1949_1960", "De 1949 à 1960"),
    ("1961_1974", "De 1961 à 1974"),
    ("1975_1993", "De 1975 à 1993"),
    ("1994_2000", "De 1994 à 2000"),
    ("2001_2010", "De 2001 à 2010"),
    ("apres_2011", "À partir de 2011"),
]


ENERGIES = [
    ("bois", "Bois de chauffage"),
    ("gaz", "Gaz naturel"),
    ("gaz_propane", "Gaz propane-butane"),
    ("fioul", "Fioul domestique"),
    ("charbon", "Charbon"),
    ("electricite", "Électricité"),
    ("autre", "Autre"),
]

ETIQUETTES = [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"), ("F", "F"), ("G", "G"),
              ("nd", "Non déterminée")]


def periode_depuis_annee(annee):
    if not annee:
        return False
    for borne, code in ((1948, "avant_1949"), (1960, "1949_1960"), (1974, "1961_1974"), (1993, "1975_1993"),
                        (2000, "1994_2000"), (2010, "2001_2010")):
        if annee <= borne:
            return code
    return "apres_2011"


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    nom_usage = fields.Char(string="Nom d'usage du syndicat")
    date_maj_rnic = fields.Date(string="Dernière mise à jour du registre national")
    type_syndicat = fields.Selection(
        [("principal", "Syndicat principal"), ("secondaire", "Syndicat secondaire"),
         ("cooperatif", "Syndicat coopératif")],
        string="Type de syndicat", default="principal")
    rnic_syndicat_principal = fields.Char(string="N° d'immatriculation du syndicat principal")
    residence_services = fields.Boolean(string="Résidence-services")
    qualite_representant = fields.Selection(
        [("mandat", "Mandat de syndic"), ("administration_provisoire", "Administration provisoire")],
        string="Représentant légal agissant en vertu d'un", default="mandat")
    periode_construction = fields.Selection(PERIODES_CONSTRUCTION, string="Période de construction")
    type_chauffage = fields.Selection(
        [("individuel", "Individuel"), ("collectif", "Collectif"), ("mixte", "Mixte"), ("aucun", "Aucun")],
        string="Type de chauffage")

    chauffage_urbain = fields.Boolean(string="Raccordé au chauffage urbain")
    energie_chauffage = fields.Selection(ENERGIES, string="Énergie du chauffage collectif ou mixte (non urbain)")
    personnel_employe = fields.Boolean(string="Le syndicat emploie un gardien ou du personnel")
    # Registre national : informations complémentaires
    adresses_complementaires = fields.Text(string="Adresse(s) complémentaire(s)")
    references_cadastrales = fields.Char(string="Références cadastrales")
    nombre_asl = fields.Integer(string="Rattachements à une ASL")
    nombre_aful = fields.Integer(string="Rattachements à une AFUL")
    nombre_unions = fields.Integer(string="Rattachements à une union de syndicats")
    ppt_vote = fields.Boolean(string="Plan pluriannuel de travaux adopté (en tout ou partie)")
    ppt_ordre_du_jour = fields.Boolean(string="Projet de plan pluriannuel inscrit à l'ordre du jour d'une AG")
    nombre_arretes = fields.Integer(string="Arrêtés de mise en sécurité / insalubrité")
    date_arrete = fields.Date(string="Date du dernier arrêté")
    date_mainlevee = fields.Date(string="Date de mainlevée")
    mandataire_ad_hoc = fields.Boolean(string="Désignation d'un mandataire ad hoc")
    date_ordonnance_ad_hoc = fields.Date(string="Date de l'ordonnance de nomination")
    date_fin_ad_hoc = fields.Date(string="Date de fin de mission")
    ordonnance_carence = fields.Boolean(string="Ordonnance de carence")
    date_ordonnance_carence = fields.Date(string="Date de l'ordonnance de carence")


class Batiment(models.Model):
    _inherit = "coproerp.batiment"

    etiquette_energie = fields.Selection(ETIQUETTES, string="Étiquette énergie (DPE)", default="nd")
