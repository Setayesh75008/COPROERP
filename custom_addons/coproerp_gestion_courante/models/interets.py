from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

COMPTE_INTERETS = "716000"  # Produits financiers


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    interets_categorie = fields.Selection(
        [("autres", "Tous les autres cas (syndicat, personne morale)"),
         ("particuliers", "Créancier personne physique")],
        string="Taux de l'intérêt légal appliqué", default="autres",
        help="Le créancier des intérêts est le syndicat, personne morale : le taux « tous les autres cas » "
             "s'applique en principe.")


class Relance(models.Model):
    _inherit = "coproerp.relance"

    interets_au = fields.Date(string="Intérêts calculés au")
    interets = fields.Float(string="Intérêts au taux légal", digits=(16, 2), readonly=True)
    interets_detail = fields.Text(string="Détail du calcul", readonly=True)
    move_interets_id = fields.Many2one("account.move", string="Écriture des intérêts", readonly=True, copy=False)

    def _point_depart_interets(self):
        self.ensure_one()
        return self.date_presentation or self.date

    def calculer_interets(self, date_fin):
        """Intérêts au taux légal sur la somme réclamée (hors frais), à compter de la mise en demeure
        (art. 36 du décret du 17 mars 1967), diminuée au fur et à mesure des règlements."""
        self.ensure_one()
        if self.type_relance != "mise_en_demeure" or self.etat != "envoyee":
            raise UserError("Les intérêts courent à compter d'une mise en demeure envoyée.")
        depart = self._point_depart_interets()
        if date_fin <= depart:
            return 0.0, []
        copro = self.copropriete_id.sudo()
        categorie = copro.interets_categorie or "autres"
        principal = max(self.montant_du - (self.frais or 0.0), 0.0)
        # Règlements postérieurs à la mise en demeure (crédits des comptes du copropriétaire)
        exclus = (self.move_frais_id | self.move_interets_id).ids
        reglements = {}
        for ligne in copro._lignes_coproprietaires([self.personne_id.id], date_max=date_fin, date_min_exclue=depart):
            if ligne.credit and ligne.move_id.id not in exclus:
                reglements[ligne.date] = reglements.get(ligne.date, 0.0) + ligne.credit
        Taux = self.env["coproerp.taux.legal"]
        total, detail = 0.0, []
        jour = depart
        while jour < date_fin and principal > 0.005:
            periode = Taux.periode_au(jour + timedelta(days=1))
            taux = periode.taux_autres if categorie == "autres" else periode.taux_particuliers
            prochains = [d for d in reglements if d > jour and d <= date_fin]
            fin = min([date_fin, periode.date_fin] + prochains)
            jours = (fin - jour).days
            montant = principal * taux / 100.0 * jours / 365.0
            total += montant
            detail.append("Du %s au %s : %.2f € × %.2f %% × %d j / 365 = %.2f €" % (
                jour.strftime("%d/%m/%Y"), fin.strftime("%d/%m/%Y"), principal, taux, jours, montant))
            principal = max(principal - reglements.get(fin, 0.0), 0.0)
            jour = fin
        return round(total, 2), detail

    def action_calculer_interets(self):
        for relance in self:
            date = relance.interets_au or fields.Date.context_today(relance)
            montant, detail = relance.calculer_interets(date)
            relance.write({"interets_au": date, "interets": montant,
                           "interets_detail": "\n".join(detail) or "Aucun intérêt"})
        return True

    def action_imputer_interets(self):
        for relance in self:
            if relance.move_interets_id:
                raise UserError("Les intérêts de cette mise en demeure ont déjà été imputés.")
            if relance.interets <= 0:
                raise UserError("Calculez d'abord les intérêts.")
            copro = relance.copropriete_id
            company = copro._verifier_dossier()
            if not copro.recouvrement_cle_frais_id:
                raise UserError("Indiquez la « clé des honoraires de recouvrement » (onglet Recouvrement) : les "
                                "intérêts perçus par le syndicat viennent en déduction des charges de cette clé.")
            libelle = "Intérêts au taux légal %s (art. 36 du décret de 1967)" % relance.name
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry", "journal_id": copro._journal("od").id, "date": relance.interets_au,
                "ref": "%s %s" % (relance.name, relance.personne_id.name or ""),
                "line_ids": [
                    Command.create({"account_id": copro._compte(copro.compte_copro_budget).id,
                                    "partner_id": relance.personne_id.id, "name": "Intérêts au taux légal",
                                    "debit": relance.interets}),
                    Command.create({"account_id": copro._compte(COMPTE_INTERETS).id,
                                    "partner_id": relance.personne_id.id, "name": libelle,
                                    "credit": relance.interets,
                                    "coproerp_repartition_id": copro.recouvrement_cle_frais_id.id}),
                ],
            })
            move.action_post()
            relance.move_interets_id = move
        return True
