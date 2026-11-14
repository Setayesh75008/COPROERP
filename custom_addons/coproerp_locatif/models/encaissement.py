from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class Encaissement(models.Model):
    """Paiement reçu d'un locataire sur le compte des mandants."""

    _name = "coproerp.locatif.encaissement"
    _description = "Encaissement de loyer"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    bail_id = fields.Many2one("coproerp.locatif.bail", string="Bail", required=True, index=True,
                              domain="[('etat', 'in', ('en_cours', 'termine'))]")
    locataire_id = fields.Many2one(related="bail_id.locataire_id", store=True, string="Locataire")
    proprietaire_id = fields.Many2one(related="bail_id.proprietaire_id", store=True, string="Propriétaire")
    date = fields.Date(string="Reçu le", required=True, default=fields.Date.context_today)
    montant = fields.Float(string="Montant", required=True, digits=(16, 2))
    mode = fields.Selection([("virement", "Virement"), ("prelevement", "Prélèvement SEPA"), ("cheque", "Chèque"),
                             ("especes", "Espèces"), ("caf", "Aide au logement (CAF, MSA) versée au bailleur"),
                             ("autre", "Autre")], string="Mode", default="virement", required=True)
    reference = fields.Char(string="Référence")
    payeur_id = fields.Many2one("res.partner", string="Payé par",
                                help="Si le paiement ne vient pas du locataire : caution, organisme, colocataire…")
    etat = fields.Selection([("brouillon", "Brouillon"), ("valide", "Validé"), ("annule", "Annulé")],
                            string="État", default="brouillon", required=True, tracking=True)
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)

    @api.constrains("montant")
    def _check_montant(self):
        for encaissement in self:
            if encaissement.montant <= 0:
                raise ValidationError("Le montant encaissé doit être positif.")

    def action_valider(self):
        dossier = self.env["coproerp.locatif.dossier"].actif()
        for enc in self.filtered(lambda e: e.etat == "brouillon"):
            if enc.name == "/":
                enc.name = self.env["ir.sequence"].next_by_code("coproerp.locatif.encaissement") or "/"
            bail = enc.bail_id
            libelle = "%s – %s – %s%s" % (enc.name, bail.locataire_id.name, dict(enc._fields["mode"].selection)[enc.mode],
                                         " %s" % enc.reference if enc.reference else "")
            banque = dossier.journal("banque").default_account_id
            enc.move_id = dossier.ecriture("banque", enc.date, libelle, [
                (banque, None, enc.montant, 0.0, libelle),
                ("locataires", bail.locataire_id, 0.0, enc.montant, libelle),
            ])
            enc.etat = "valide"
            bail.lettrer()
        return True

    def action_annuler(self):
        for enc in self.filtered(lambda e: e.etat == "valide"):
            lignes = enc.move_id.sudo().line_ids
            lignes.remove_move_reconcile()
            enc.move_id.sudo()._reverse_moves([{"date": enc.date, "ref": "Annulation %s" % enc.name}], cancel=True)
            enc.etat = "annule"
            enc.bail_id.lettrer()
            enc.bail_id.echeance_ids._maj_paiement()
        return True

    def unlink(self):
        if any(e.etat != "brouillon" for e in self):
            raise UserError("Un encaissement validé ne se supprime pas : annulez-le.")
        return super().unlink()
