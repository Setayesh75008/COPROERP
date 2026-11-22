from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .depense import _euros


class Reversement(models.Model):
    """Virement depuis le compte des mandants : au propriétaire, ou des honoraires au cabinet."""

    _name = "coproerp.locatif.reversement"
    _description = "Virement des fonds des mandants"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    type_reversement = fields.Selection([("proprietaire", "Au propriétaire"),
                                         ("honoraires", "Honoraires au cabinet")],
                                        string="Virement", default="proprietaire", required=True)
    mandat_id = fields.Many2one("coproerp.locatif.mandat", string="Mandat", index=True,
                                domain="[('etat', '!=', 'brouillon')]")
    proprietaire_id = fields.Many2one(related="mandat_id.proprietaire_id", store=True, string="Propriétaire")
    compte_rendu_id = fields.Many2one("coproerp.locatif.compte_rendu", string="Compte rendu", readonly=True,
                                      ondelete="set null")
    iban = fields.Char(string="IBAN du bénéficiaire", compute="_compute_iban", store=True, readonly=False)
    date = fields.Date(string="Date du virement", required=True, default=fields.Date.context_today)
    montant = fields.Float(string="Montant", required=True, digits=(16, 2))
    disponible = fields.Float(string="Disponible à ce jour", compute="_compute_disponible", digits=(16, 2))
    etat = fields.Selection([("brouillon", "À virer"), ("valide", "Viré"), ("annule", "Annulé")], string="État",
                            default="brouillon", required=True, tracking=True)
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)

    @api.depends("mandat_id", "type_reversement")
    def _compute_iban(self):
        for rev in self:
            if rev.type_reversement == "proprietaire" and rev.mandat_id and not rev.iban:
                rev.iban = rev.mandat_id.iban_proprietaire
            else:
                rev.iban = rev.iban

    @api.depends("mandat_id", "type_reversement")
    def _compute_disponible(self):
        Mandat = self.env["coproerp.locatif.mandat"]
        for rev in self:
            if rev.type_reversement == "honoraires":
                rev.disponible = Mandat.solde_compte(None, "honoraires")
            elif rev.mandat_id:
                rev.disponible = Mandat.situation_proprietaire(rev.proprietaire_id)["utilisable"]
            else:
                rev.disponible = 0.0

    @api.constrains("montant", "type_reversement", "mandat_id")
    def _check_montant(self):
        for rev in self:
            if rev.montant <= 0:
                raise ValidationError("Le montant du virement doit être positif.")
            if rev.type_reversement == "proprietaire" and not rev.mandat_id:
                raise ValidationError("Indiquez le mandat du propriétaire à qui virer les fonds.")

    def action_valider(self):
        dossier = self.env["coproerp.locatif.dossier"].actif().with_context(locatif_nature="reversement")
        Mandat = self.env["coproerp.locatif.mandat"]
        banque = dossier.journal("banque").default_account_id
        for rev in self.filtered(lambda r: r.etat == "brouillon"):
            if rev.type_reversement == "proprietaire":
                situation = Mandat.situation_proprietaire(rev.proprietaire_id)
                if rev.montant > situation["utilisable"] + 0.004:
                    raise UserError(
                        "Le virement de %s à %s dépasse ses fonds réellement encaissés : %s (solde de son compte "
                        "%s, dont %s de loyers non encore payés par les locataires)."
                        % (_euros(rev.montant), rev.proprietaire_id.name, _euros(situation["utilisable"]),
                           _euros(situation["solde"]), _euros(situation["impayes"])))
                if not rev.iban:
                    raise UserError("Indiquez l'IBAN du propriétaire (sur le mandat ou sur le virement).")
                cle, tiers, objet = "proprietaires", rev.proprietaire_id, rev.proprietaire_id.name
            else:
                solde = Mandat.solde_compte(None, "honoraires")
                if rev.montant > solde + 0.004:
                    raise UserError("Seuls %s d'honoraires ont été prélevés et restent à virer au cabinet."
                                    % _euros(solde))
                cle, tiers, objet = "honoraires", None, "honoraires de gestion du cabinet"
            if rev.name == "/":
                rev.name = self.env["ir.sequence"].next_by_code("coproerp.locatif.reversement") or "/"
            libelle = "%s – Virement %s" % (rev.name, objet)
            nature = "reversement" if rev.type_reversement == "proprietaire" else "honoraires_cabinet"
            rev.move_id = dossier.with_context(locatif_nature=nature).ecriture("banque", rev.date, libelle, [
                (cle, tiers, rev.montant, 0.0, libelle),
                (banque, None, 0.0, rev.montant, libelle),
            ])
            rev.etat = "valide"
        return True

    def action_annuler(self):
        for rev in self.filtered(lambda r: r.etat == "valide"):
            rev.move_id.sudo()._reverse_moves([{"date": rev.date, "ref": "Annulation %s" % rev.name}], cancel=True)
            rev.etat = "annule"
        return True

    @api.model
    def action_preparer_honoraires(self):
        """Prépare le virement au cabinet des honoraires prélevés et non encore virés."""
        solde = self.env["coproerp.locatif.mandat"].solde_compte(None, "honoraires")
        if solde <= 0:
            raise UserError("Aucun honoraire prélevé n'est en attente de virement au cabinet.")
        rev = self.create({"type_reversement": "honoraires", "montant": solde})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": rev.id, "view_mode": "form"}

    def unlink(self):
        if any(r.etat != "brouillon" for r in self):
            raise UserError("Un virement validé ne se supprime pas : annulez-le.")
        return super().unlink()
