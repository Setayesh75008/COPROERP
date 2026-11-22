from datetime import date

from odoo import api, models

from .depense import CATEGORIES


class RapportRecapFiscal(models.AbstractModel):
    """Récapitulatif annuel, par propriétaire, des sommes utiles à la déclaration des revenus fonciers."""

    _name = "report.coproerp_locatif_reversement.report_recap_fiscal"
    _description = "Récapitulatif annuel des revenus fonciers"

    @api.model
    def _get_report_values(self, docids, data=None):
        annee = int((data or {}).get("annee") or date.today().year - 1)
        proprietaires = self.env["res.partner"].browse(docids or (data or {}).get("proprietaire_ids", []))
        return {"doc_ids": proprietaires.ids, "doc_model": "res.partner", "docs": proprietaires, "annee": annee,
                "recaps": {p.id: self.recap(p, annee) for p in proprietaires},
                "euros": self.env["coproerp.locatif.bail"].euros}

    @api.model
    def recap(self, proprietaire, annee):
        debut, fin = date(annee, 1, 1), date(annee, 12, 31)
        dossier = self.env["coproerp.locatif.mandat"].dossier_mandants()
        compte_locataires = dossier.compte("locataires") if dossier else False
        Echeance = self.env["coproerp.locatif.echeance"].sudo()
        baux = self.env["coproerp.locatif.bail"].sudo().search([("proprietaire_id", "=", proprietaire.id),
                                                                ("etat", "!=", "brouillon")])
        par_bail, totaux = [], {"loyers": 0.0, "charges": 0.0, "tva": 0.0, "depot": 0.0, "avances": 0.0}
        for bail in baux:
            ligne_bail = {"bail": bail, "loyers": 0.0, "charges": 0.0, "tva": 0.0, "depot": 0.0, "avances": 0.0}
            encaissements = bail.encaissement_ids.filtered(lambda e: e.etat == "valide" and debut <= e.date <= fin)
            for enc in encaissements:
                impute = 0.0
                for ligne in enc.move_id.sudo().line_ids.filtered(lambda l: l.account_id == compte_locataires):
                    for partiel in ligne.matched_debit_ids:
                        avis = Echeance.search([("move_id", "=", partiel.debit_move_id.move_id.id)], limit=1)
                        impute += partiel.amount
                        if not avis or avis.montant_total <= 0:
                            ligne_bail["loyers"] += partiel.amount
                            continue
                        # Le paiement se répartit entre loyer, charges, TVA… à proportion de l'avis payé.
                        for l in avis.ligne_ids:
                            part = partiel.amount * l.montant / avis.montant_total
                            if l.type_ligne == "charges":
                                ligne_bail["charges"] += part
                            elif l.type_ligne == "tva":
                                ligne_bail["tva"] += part
                            elif l.type_ligne == "depot":
                                ligne_bail["depot"] += part
                            else:  # loyer, forfait de charges (imposable comme le loyer), autre
                                ligne_bail["loyers"] += part
                ligne_bail["avances"] += enc.montant - impute
            for cle in totaux:
                ligne_bail[cle] = round(ligne_bail[cle], 2)
                totaux[cle] += ligne_bail[cle]
            if encaissements or bail.etat == "en_cours":
                par_bail.append(ligne_bail)

        depenses = self.env["coproerp.locatif.depense"].sudo().search([
            ("proprietaire_id", "=", proprietaire.id), ("etat", "=", "payee"),
            ("date_paiement", ">=", debut), ("date_paiement", "<=", fin)])
        par_categorie = []
        for cle, libelle in CATEGORIES:
            montant = round(sum(depenses.filtered(lambda d: d.categorie == cle).mapped("montant")), 2)
            if montant:
                par_categorie.append({"cle": cle, "libelle": libelle, "montant": montant,
                                      "detail": depenses.filtered(lambda d: d.categorie == cle)})

        honoraires = 0.0
        if dossier:
            lignes = self.env["account.move.line"].sudo().search([
                ("company_id", "=", dossier.company_id.id), ("account_id", "=", dossier.compte("proprietaires").id),
                ("partner_id", "=", proprietaire.id), ("parent_state", "=", "posted"),
                ("move_id.locatif_nature", "=", "honoraires"), ("date", ">=", debut), ("date", "<=", fin)])
            honoraires = round(sum(lignes.mapped("balance")), 2)

        biens = baux.filtered(lambda b: b.date_debut <= fin and (not b.date_sortie or b.date_sortie >= debut)).bien_id
        return {
            "par_bail": par_bail, "totaux": {k: round(v, 2) for k, v in totaux.items()},
            "depenses": par_categorie, "total_depenses": round(sum(d["montant"] for d in par_categorie), 2),
            "honoraires": honoraires, "nombre_locaux": len(biens),
            "commercial": any(b.tva for b in baux),
        }
