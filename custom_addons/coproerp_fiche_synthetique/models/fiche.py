import base64

from odoo import api, fields, models
from odoo.exceptions import UserError

import json

from .copropriete import ENERGIES, ETIQUETTES, PERIODES_CONSTRUCTION, periode_depuis_annee

SEUIL_DEBITEUR = 300.0          # copropriétaires débiteurs de plus de 300 €
PETITE_COPRO_LOTS = 10          # dispense : moins de 10 lots…
PETITE_COPRO_BUDGET = 15000.0   # … et budget moyen inférieur à 15 000 €


class FicheSynthetique(models.Model):
    """Fiche synthétique de la copropriété (art. 8-2 de la loi, décret n° 2016-1822).

    Les valeurs sont calculées puis enregistrées (modifiables) : la fiche reste ainsi
    identique à celle remise, même si les comptes évoluent ensuite.
    """

    _name = "coproerp.fiche.synthetique"
    _description = "Fiche synthétique de la copropriété"
    _inherit = ["mail.thread"]
    _order = "date_etablissement desc, id desc"

    name = fields.Char(string="Libellé", compute="_compute_name", store=True)
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="restrict")
    date_etablissement = fields.Date(string="Établie le", required=True, default=fields.Date.context_today)
    cloture_id = fields.Many2one(
        "coproerp.cloture", string="Exercice approuvé", domain="[('copropriete_id', '=', copropriete_id)]",
        help="Exercice dont les comptes ont été approuvés par l'assemblée générale.")
    date_approbation = fields.Date(string="Comptes approuvés par l'assemblée du")
    etat = fields.Selection(
        [("brouillon", "En préparation"), ("etablie", "Établie"), ("publiee", "Mise à disposition (extranet)")],
        string="État", default="brouillon", required=True, readonly=True, copy=False, tracking=True)
    document_id = fields.Many2one("coproerp.extranet.document", string="Document extranet", readonly=True, copy=False)

    # 1. Identification du syndicat
    nom_usage = fields.Char(string="Nom d'usage")
    adresse = fields.Text(string="Adresse de l'immeuble")
    adresses_complementaires = fields.Text(string="Adresse(s) complémentaire(s)")
    numero_rnic = fields.Char(string="N° d'immatriculation")
    date_immatriculation = fields.Date(string="Date d'immatriculation")
    references_cadastrales = fields.Char(string="Références cadastrales")
    date_maj_rnic = fields.Date(string="Dernière mise à jour du registre")
    date_reglement = fields.Date(string="Date d'établissement du règlement de copropriété")
    siret_syndicat = fields.Char(string="N° SIRET du syndicat")
    # 2. Représentant légal
    representant = fields.Char(string="Syndic (nom ou raison sociale)")
    representant_adresse = fields.Text(string="Adresse du syndic")
    representant_siret = fields.Char(string="N° SIRET du syndic")
    representant_telephone = fields.Char(string="Téléphone du syndic")
    mandat_debut = fields.Date(string="Début du mandat")
    mandat_fin = fields.Date(string="Fin du mandat")
    qualite_representant = fields.Selection(
        [("mandat", "Mandat de syndic"), ("administration_provisoire", "Administration provisoire")],
        string="Agissant en vertu d'un")
    # 3. Organisation juridique
    type_syndicat = fields.Selection(
        [("principal", "Syndicat principal"), ("secondaire", "Syndicat secondaire"),
         ("cooperatif", "Syndicat coopératif")], string="Type de syndicat")
    rnic_syndicat_principal = fields.Char(string="Immatriculation du syndicat principal")
    residence_services = fields.Boolean(string="Résidence-services")
    nombre_asl = fields.Integer(string="ASL")
    nombre_aful = fields.Integer(string="AFUL")
    nombre_unions = fields.Integer(string="Unions de syndicats")
    # 4. Caractéristiques techniques
    nombre_lots = fields.Integer(string="Nombre total de lots")
    lots_habitation = fields.Integer(string="Lots à usage d'habitation")
    lots_commerces = fields.Integer(string="Lots à usage de commerces")
    lots_bureaux = fields.Integer(string="Lots à usage de bureaux")
    lots_principaux = fields.Integer(string="Lots à usage d'habitation, de commerces et de bureaux")
    lots_stationnement = fields.Integer(string="Lots de stationnement")
    etiquettes = fields.Char(string="Bâtiments par étiquette énergie")
    ppt_vote = fields.Boolean(string="Plan pluriannuel de travaux adopté")
    ppt_ordre_du_jour = fields.Boolean(string="Projet de plan pluriannuel inscrit à l'ordre du jour")
    nombre_batiments = fields.Integer(string="Nombre de bâtiments")
    periode_construction = fields.Selection(PERIODES_CONSTRUCTION, string="Période de construction")
    # 5. Équipements
    type_chauffage = fields.Selection(
        [("individuel", "Individuel"), ("collectif", "Collectif"), ("mixte", "Mixte"), ("aucun", "Aucun")],
        string="Type de chauffage")
    chauffage_urbain = fields.Boolean(string="Chauffage urbain")
    energie = fields.Selection(ENERGIES, string="Énergie (chauffage collectif ou mixte, non urbain)")
    nombre_ascenseurs = fields.Integer(string="Nombre d'ascenseurs")
    # 6. Caractéristiques financières
    personnel_employe = fields.Boolean(string="Personnel employé par le syndicat")
    exercice_debut = fields.Date(string="Début de l'exercice")
    exercice_fin = fields.Date(string="Fin de l'exercice")
    charges_courantes = fields.Float(string="Charges pour opérations courantes", digits=(16, 2))
    charges_travaux = fields.Float(string="Charges pour travaux et opérations exceptionnelles", digits=(16, 2))
    dettes = fields.Float(string="Dettes fournisseurs, rémunérations et autres", digits=(16, 2))
    impayes = fields.Float(string="Sommes restant dues par les copropriétaires", digits=(16, 2))
    debiteurs_300 = fields.Integer(string="Copropriétaires débiteurs de plus de 300 €")
    fonds_travaux = fields.Float(string="Montant du fonds de travaux", digits=(16, 2))
    nombre_arretes = fields.Integer(string="Arrêtés de mise en sécurité / insalubrité")
    date_arrete = fields.Date(string="Date de l'arrêté")
    date_mainlevee = fields.Date(string="Date de mainlevée")
    mandataire_ad_hoc = fields.Boolean(string="Mandataire ad hoc")
    date_ordonnance_ad_hoc = fields.Date(string="Ordonnance de nomination du")
    date_fin_ad_hoc = fields.Date(string="Fin de mission le")
    ordonnance_carence = fields.Boolean(string="Ordonnance de carence")
    date_ordonnance_carence = fields.Date(string="Ordonnance de carence du")
    # Attestation délivrée par le registre (téléchargée sur le site du registre)
    attestation_fichier = fields.Binary(string="Attestation du registre (PDF)", attachment=True, copy=False)
    attestation_nom = fields.Char(string="Nom du fichier", copy=False)
    attestation_document_id = fields.Many2one(
        "coproerp.extranet.document", string="Attestation sur l'extranet", readonly=True, copy=False)
    dispense_impayes = fields.Boolean(
        string="Petite copropriété (impayés non mentionnés)",
        help="Moins de 10 lots et budget prévisionnel moyen inférieur à 15 000 € sur les trois derniers "
             "exercices : les impayés et le nombre de débiteurs ne figurent pas sur la fiche.")

    @api.depends("copropriete_id", "date_etablissement")
    def _compute_name(self):
        for fiche in self:
            fiche.name = "Fiche synthétique %s – %s" % (
                fiche.copropriete_id.name or "", fiche.date_etablissement.strftime("%d/%m/%Y")
                if fiche.date_etablissement else "")

    @api.model_create_multi
    def create(self, vals_list):
        fiches = super().create(vals_list)
        for fiche in fiches:
            if not fiche.cloture_id:
                fiche.cloture_id = self.env["coproerp.cloture"].search(
                    [("copropriete_id", "=", fiche.copropriete_id.id)], order="date_fin desc", limit=1)
            fiche.action_calculer()
        return fiches

    def write(self, vals):
        libres = {"etat", "document_id", "attestation_fichier", "attestation_nom", "attestation_document_id"}
        if self.filtered(lambda f: f.etat == "publiee") and set(vals) - libres:
            raise UserError("Cette fiche est publiée : établissez une nouvelle fiche pour la mettre à jour.")
        return super().write(vals)

    # ------------------------------------------------------------------
    def _valeurs_identification(self):
        copro = self.copropriete_id.sudo()
        syndic = copro.syndic_id
        lots = self.env["coproerp.lot"].search([("copropriete_id", "=", copro.id)])
        batiments = self.env["coproerp.batiment"].search([("copropriete_id", "=", copro.id)])
        adresse_syndic = "\n".join(x for x in [
            syndic.street, syndic.street2, " ".join(y for y in [syndic.zip, syndic.city] if y)] if x) if syndic else False
        return {
            "nom_usage": copro.nom_usage or copro.name,
            "adresse": "\n".join(x for x in [copro.street, " ".join(y for y in [copro.zip, copro.city] if y)] if x),
            "adresses_complementaires": copro.adresses_complementaires,
            "numero_rnic": copro.numero_rnc,
            "date_immatriculation": copro.date_immatriculation,
            "references_cadastrales": copro.references_cadastrales,
            "date_maj_rnic": copro.date_maj_rnic or copro.date_immatriculation,
            "date_reglement": copro.date_reglement,
            "siret_syndicat": copro.siret,
            "representant": syndic.name if syndic else False,
            "representant_adresse": adresse_syndic,
            "representant_siret": (syndic.company_registry or False) if syndic else False,
            "representant_telephone": (syndic.phone or False) if syndic else False,
            "mandat_debut": copro.date_debut_contrat,
            "mandat_fin": copro.date_fin_contrat,
            "nombre_asl": copro.nombre_asl,
            "nombre_aful": copro.nombre_aful,
            "nombre_unions": copro.nombre_unions,
            "lots_principaux": len(lots.filtered(lambda l: l.usage in ("appartement", "local", "bureau"))),
            "lots_stationnement": len(lots.filtered(lambda l: l.usage == "parking")),
            "etiquettes": json.dumps({cle: len(batiments.filtered(lambda b, c=cle: (b.etiquette_energie or "nd") == c))
                                      for cle, _l in ETIQUETTES}),
            "ppt_vote": copro.ppt_vote,
            "ppt_ordre_du_jour": copro.ppt_ordre_du_jour,
            "chauffage_urbain": copro.chauffage_urbain,
            "energie": copro.energie_chauffage,
            "nombre_arretes": copro.nombre_arretes,
            "date_arrete": copro.date_arrete,
            "date_mainlevee": copro.date_mainlevee,
            "mandataire_ad_hoc": copro.mandataire_ad_hoc,
            "date_ordonnance_ad_hoc": copro.date_ordonnance_ad_hoc,
            "date_fin_ad_hoc": copro.date_fin_ad_hoc,
            "ordonnance_carence": copro.ordonnance_carence,
            "date_ordonnance_carence": copro.date_ordonnance_carence,
            "qualite_representant": copro.qualite_representant or "mandat",
            "type_syndicat": copro.type_syndicat or "principal",
            "rnic_syndicat_principal": copro.rnic_syndicat_principal,
            "residence_services": copro.residence_services,
            "nombre_lots": len(lots),
            "lots_habitation": len(lots.filtered(lambda l: l.usage == "appartement")),
            "lots_commerces": len(lots.filtered(lambda l: l.usage == "local")),
            "lots_bureaux": len(lots.filtered(lambda l: l.usage == "bureau")),
            "nombre_batiments": len(batiments),
            "periode_construction": copro.periode_construction or periode_depuis_annee(copro.annee_construction),
            "type_chauffage": copro.type_chauffage,
            "nombre_ascenseurs": copro.nombre_ascenseurs,
            "personnel_employe": copro.personnel_employe or bool(copro.nombre_gardiens),
        }

    def _valeurs_financieres(self):
        cloture = self.cloture_id
        if not cloture:
            return {}
        copro = self.copropriete_id.sudo()
        annexes = cloture.donnees_annexes()
        etat = annexes["annexe1"]["n"]
        # Copropriétaires débiteurs de plus de 300 € à la fin de l'exercice
        lignes = copro._lignes_coproprietaires(date_max=cloture.date_fin)
        soldes = {}
        for ligne in lignes:
            soldes[ligne.partner_id] = soldes.get(ligne.partner_id, 0.0) + ligne.balance
        budgets = self.env["coproerp.budget.annuel"].search([
            ("copropriete_id", "=", copro.id), ("date_fin", "<=", cloture.date_fin)], order="date_fin desc", limit=3)
        montants = [sum(b.ligne_ids.mapped("montant_annuel")) or b.budget_previsionnel for b in budgets]
        budget_moyen = sum(montants) / len(montants) if montants else 0.0
        ag = self.env["coproerp.ag"].search([
            ("cloture_id", "=", cloture.id), ("etat", "=", "tenue")], order="date_ag desc", limit=1)
        valeurs = {
            "exercice_debut": cloture.date_debut,
            "exercice_fin": cloture.date_fin,
            "charges_courantes": annexes["annexe2"]["courant"]["total_charges"]["n"],
            "charges_travaux": annexes["annexe2"]["travaux"]["total_charges"]["n"],
            "dettes": round(sum(etat.get(k, 0.0) for k in (
                "dette_40", "dette_42", "dette_46", "dette_47", "dette_48")), 2),
            "impayes": round(etat.get("creance_45", 0.0) + etat.get("creance_459", 0.0), 2),
            "debiteurs_300": len([s for p, s in soldes.items() if p and s > SEUIL_DEBITEUR]),
            "fonds_travaux": etat.get("fonds_105", 0.0),
            "dispense_impayes": len(self.env["coproerp.lot"].search([("copropriete_id", "=", copro.id)]))
            < PETITE_COPRO_LOTS and budget_moyen < PETITE_COPRO_BUDGET,
        }
        if ag and not self.date_approbation:
            valeurs["date_approbation"] = ag.date_ag
        return valeurs

    def action_calculer(self):
        for fiche in self:
            if fiche.etat == "publiee":
                raise UserError("Cette fiche est publiée : établissez une nouvelle fiche.")
            valeurs = fiche._valeurs_identification()
            valeurs.update(fiche._valeurs_financieres())
            super(FicheSynthetique, fiche).write(valeurs)
        return True

    def action_etablir(self):
        self.filtered(lambda f: f.etat == "brouillon").write({"etat": "etablie"})
        return True

    def action_remettre_brouillon(self):
        self.filtered(lambda f: f.etat == "etablie").write({"etat": "brouillon"})
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_fiche_synthetique.action_report_fiche_synthetique").report_action(self)

    def action_publier_extranet(self):
        """Met la fiche à disposition de tous les copropriétaires sur l'extranet."""
        rapport = self.env.ref("coproerp_fiche_synthetique.action_report_fiche_synthetique")
        categorie = self.env.ref("coproerp_extranet.categorie_fiche_synthetique")
        for fiche in self:
            if fiche.etat == "brouillon":
                raise UserError("Établissez d'abord la fiche.")
            pdf, _type = self.env["ir.actions.report"]._render_qweb_pdf(rapport.report_name, fiche.ids)
            document = self.env["coproerp.extranet.document"].create({
                "name": "Fiche synthétique de la copropriété (%s)" % fiche.date_etablissement.strftime("%d/%m/%Y"),
                "copropriete_id": fiche.copropriete_id.id,
                "categorie_id": categorie.id,
                "visibilite": "tous",
                "fichier": base64.b64encode(pdf),
                "nom_fichier": "Fiche synthetique %s.pdf" % fiche.date_etablissement.strftime("%Y-%m-%d"),
                "date_document": fiche.date_etablissement,
            })
            document.action_publier()
            super(FicheSynthetique, fiche).write({"etat": "publiee", "document_id": document.id})
        return True

    def action_publier_attestation(self):
        """Met l'attestation d'immatriculation (téléchargée sur le site du registre) sur l'extranet."""
        categorie = self.env.ref("coproerp_extranet.categorie_immatriculation")
        for fiche in self:
            if not fiche.attestation_fichier:
                raise UserError("Joignez d'abord l'attestation téléchargée sur le site du registre des copropriétés.")
            document = self.env["coproerp.extranet.document"].create({
                "name": "Attestation d'immatriculation – mise à jour annuelle (%s)" % (
                    fiche.exercice_fin.year if fiche.exercice_fin else fiche.date_etablissement.year),
                "copropriete_id": fiche.copropriete_id.id,
                "categorie_id": categorie.id,
                "visibilite": "tous",
                "fichier": fiche.attestation_fichier,
                "nom_fichier": fiche.attestation_nom or "Attestation d'immatriculation.pdf",
                "date_document": fields.Date.context_today(fiche),
            })
            document.action_publier()
            super(FicheSynthetique, fiche).write({"attestation_document_id": document.id})
        return True

    def action_imprimer_declaration(self):
        return self.env.ref("coproerp_fiche_synthetique.action_report_declaration_registre").report_action(self)

    # -- aides d'impression ----------------------------------------------
    def coche(self, condition):
        return "☒" if condition else "☐"

    def etiquettes_liste(self):
        self.ensure_one()
        valeurs = json.loads(self.etiquettes or "{}")
        return [(libelle, valeurs.get(cle, 0)) for cle, libelle in ETIQUETTES]

    def energies_liste(self):
        return ENERGIES

    def oui_non(self, valeur):
        return "Oui" if valeur else "Non"

    def fmt(self, valeur):
        return "{:,.2f}".format(valeur or 0.0).replace(",", " ").replace(".", ",") + " €"

    def libelle(self, champ):
        self.ensure_one()
        valeur = self[champ]
        return dict(self._fields[champ].selection).get(valeur, "") if valeur else "Non renseigné"

    def date_fr(self, champ):
        self.ensure_one()
        return self[champ].strftime("%d/%m/%Y") if self[champ] else "Non renseignée"
