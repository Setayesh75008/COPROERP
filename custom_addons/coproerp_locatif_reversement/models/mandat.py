from odoo import api, fields, models


class MandatGestion(models.Model):
    _inherit = "coproerp.locatif.mandat"

    reserve = fields.Float(
        string="Réserve conservée", digits=(16, 2), default=0.0,
        help="Somme gardée sur le compte du propriétaire pour régler ses factures (charges de copropriété, "
             "petites réparations) : elle n'est pas virée avec ses loyers.")
    solde_proprietaire = fields.Float(string="Solde du compte du propriétaire", compute="_compute_situation",
                                      digits=(16, 2))
    impayes_proprietaire = fields.Float(string="Dont loyers non encore encaissés", compute="_compute_situation",
                                        digits=(16, 2))
    disponible = fields.Float(string="Disponible à virer", compute="_compute_situation", digits=(16, 2))
    compte_rendu_ids = fields.One2many("coproerp.locatif.compte_rendu", "mandat_id", string="Comptes rendus")

    def _compute_situation(self):
        for mandat in self:
            situation = self.situation_proprietaire(mandat.proprietaire_id)
            mandat.solde_proprietaire = situation["solde"]
            mandat.impayes_proprietaire = situation["impayes"]
            mandat.disponible = situation["disponible"]

    # ------------------------------------------------------------------
    @api.model
    def dossier_mandants(self):
        return self.env["coproerp.locatif.dossier"].sudo().search([("company_id", "!=", False)], limit=1)

    @api.model
    def solde_compte(self, partner, cle="proprietaires", au=None):
        """Solde créditeur (ce que les mandants détiennent) du sous-compte d'un tiers."""
        dossier = self.dossier_mandants()
        if not dossier:
            return 0.0
        domaine = [("company_id", "=", dossier.company_id.id), ("account_id", "=", dossier.compte(cle).id),
                   ("parent_state", "=", "posted")]
        if partner is not None:
            domaine.append(("partner_id", "=", partner.id))
        if au:
            domaine.append(("date", "<=", au))
        lignes = self.env["account.move.line"].sudo().search(domaine)
        return round(-sum(lignes.mapped("balance")), 2)

    @api.model
    def impayes(self, partner):
        """Sommes portées au crédit du propriétaire mais pas encore payées par ses locataires."""
        avis = self.env["coproerp.locatif.echeance"].sudo().search([
            ("proprietaire_id", "=", partner.id), ("annulee", "=", False), ("montant_restant", ">", 0)])
        avis = avis.filtered(lambda a: not (a.type_echeance == "depot" and a.bail_id.mandat_id.depot_conserve))
        return round(sum(avis.mapped("montant_restant")), 2)

    @api.model
    def situation_proprietaire(self, partner):
        """Solde du compte, loyers non encaissés et somme disponible d'un propriétaire.

        Les fonds d'un mandant ne servent qu'à lui : on ne vire ni ne paie au-delà de ce qui a été
        réellement encaissé pour lui.
        """
        solde = self.solde_compte(partner)
        impayes = self.impayes(partner)
        reserve = sum(self.search([("proprietaire_id", "=", partner.id), ("etat", "=", "actif")]).mapped("reserve"))
        utilisable = round(solde - impayes, 2)
        return {"solde": solde, "impayes": impayes, "reserve": reserve, "utilisable": max(utilisable, 0.0),
                "disponible": max(round(utilisable - reserve, 2), 0.0)}

    def action_voir_comptes_rendus(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": "Comptes rendus de gestion",
                "res_model": "coproerp.locatif.compte_rendu", "view_mode": "list,form",
                "domain": [("mandat_id", "=", self.id)], "context": {"default_mandat_id": self.id}}

    def action_preparer_virement(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": "Virement au propriétaire",
                "res_model": "coproerp.locatif.reversement", "view_mode": "form", "target": "current",
                "context": {"default_mandat_id": self.id, "default_montant": self.disponible}}
