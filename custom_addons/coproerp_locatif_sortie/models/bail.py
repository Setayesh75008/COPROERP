from odoo import fields, models


class Bail(models.Model):
    _inherit = "coproerp.locatif.bail"

    etat_lieux_ids = fields.One2many("coproerp.locatif.etat_lieux", "bail_id", string="États des lieux")
    sortie_ids = fields.One2many("coproerp.locatif.sortie", "bail_id", string="Décompte de sortie")

    def _lignes_compte_locataire(self):
        """Ajoute au compte du locataire les écritures de sa sortie (dépôt imputé, restitution, majoration)."""
        lignes = super()._lignes_compte_locataire()
        moves = self.sortie_ids.filtered(lambda s: s.etat != "annule").move_ids
        if moves:
            dossier = self.env["coproerp.locatif.mandat"].dossier_mandants()
            compte = dossier.compte("locataires")
            lignes |= moves.sudo().line_ids.filtered(
                lambda l: l.account_id == compte and l.partner_id == self.locataire_id and not l.reconciled
                and l.parent_state == "posted")
        return lignes

    def action_etat_des_lieux(self):
        self.ensure_one()
        entree = self.etat_lieux_ids.filtered(lambda e: e.type_edl == "entree" and e.etat == "signe")
        return {"type": "ir.actions.act_window", "name": "États des lieux", "res_model": "coproerp.locatif.etat_lieux",
                "view_mode": "list,form", "domain": [("bail_id", "=", self.id)],
                "context": {"default_bail_id": self.id, "default_type_edl": "sortie" if entree else "entree"}}

    def action_sortie(self):
        self.ensure_one()
        sortie = self.sortie_ids.filtered(lambda s: s.etat != "annule")[:1]
        action = {"type": "ir.actions.act_window", "name": "Sortie du locataire",
                  "res_model": "coproerp.locatif.sortie", "view_mode": "form"}
        if sortie:
            action["res_id"] = sortie.id
        else:
            action["context"] = {"default_bail_id": self.id, "default_date_remise_cles": self.date_sortie
                                 or fields.Date.context_today(self)}
        return action
