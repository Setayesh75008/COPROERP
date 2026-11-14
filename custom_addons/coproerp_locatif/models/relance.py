from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

TYPES_RELANCE = [
    ("relance", "Relance amiable"),
    ("mise_en_demeure", "Mise en demeure"),
    ("information_garant", "Information de la caution"),
]


class RelanceLocataire(models.Model):
    """Lettre de relance, de mise en demeure ou d'information de la caution pour un loyer impayé."""

    _name = "coproerp.locatif.relance"
    _description = "Relance d'un locataire"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    bail_id = fields.Many2one("coproerp.locatif.bail", string="Bail", required=True, index=True)
    type_relance = fields.Selection(TYPES_RELANCE, string="Type", required=True, default="relance", tracking=True)
    destinataire_id = fields.Many2one("res.partner", string="Destinataire", required=True)
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    montant_du = fields.Float(string="Montant réclamé", digits=(16, 2), readonly=True)
    echeance_ids = fields.Many2many("coproerp.locatif.echeance", string="Échéances impayées", readonly=True)
    delai_jours = fields.Integer(string="Délai accordé (jours)", default=8)
    mode_envoi = fields.Selection([("courrier", "Courrier simple"), ("email", "Courriel"),
                                   ("lrar", "Lettre recommandée avec AR")], string="Envoi", default="courrier",
                                  required=True)
    numero_envoi = fields.Char(string="N° de recommandé")
    date_presentation = fields.Date(string="Première présentation le")
    etat = fields.Selection([("brouillon", "À envoyer"), ("envoyee", "Envoyée"), ("annulee", "Annulée")],
                            string="État", default="brouillon", required=True, tracking=True)

    @api.onchange("type_relance", "bail_id")
    def _onchange_type(self):
        if self.type_relance == "information_garant" and self.bail_id.garant_ids:
            self.destinataire_id = self.bail_id.garant_ids[:1]
        elif self.bail_id:
            self.destinataire_id = self.bail_id.locataire_id
        if self.type_relance in ("mise_en_demeure", "information_garant"):
            self.mode_envoi = "lrar"

    @api.model
    def preparer(self, bail):
        """Prépare la lettre adaptée au stade de l'impayé."""
        if bail.solde <= 0:
            raise UserError("Le locataire du bail %s n'a pas d'impayé." % bail.name)
        derniere = self.search([("bail_id", "=", bail.id), ("etat", "=", "envoyee"),
                                ("type_relance", "in", ("relance", "mise_en_demeure"))], limit=1)
        dossier = self.env["coproerp.locatif.dossier"].actif()
        type_relance = "relance"
        if derniere and derniere.type_relance == "relance" and \
                derniere.date + timedelta(days=dossier.jours_avant_mise_en_demeure) <= fields.Date.context_today(self):
            type_relance = "mise_en_demeure"
        elif derniere and derniere.type_relance == "mise_en_demeure":
            type_relance = "mise_en_demeure"
        return self.create({
            "bail_id": bail.id, "type_relance": type_relance, "destinataire_id": bail.locataire_id.id,
            "mode_envoi": "lrar" if type_relance == "mise_en_demeure" else "courrier",
            "delai_jours": 8 if type_relance == "relance" else 15,
        })

    def _impayes(self):
        self.ensure_one()
        return self.bail_id.echeance_ids.filtered(
            lambda e: e.etat in ("emise", "partielle") and e.date_echeance <= self.date).sorted("date_echeance")

    def action_envoyer(self):
        for relance in self.filtered(lambda r: r.etat == "brouillon"):
            impayes = relance._impayes()
            montant = round(sum(impayes.mapped("montant_restant")), 2)
            if montant <= 0:
                raise UserError("Aucune échéance exigible n'est impayée à cette date.")
            if relance.type_relance == "information_garant" and relance.destinataire_id not in relance.bail_id.garant_ids:
                raise UserError("Le destinataire n'est pas un garant du bail.")
            relance.write({
                "name": self.env["ir.sequence"].next_by_code("coproerp.locatif.relance") or "/",
                "montant_du": montant, "echeance_ids": [(6, 0, impayes.ids)], "etat": "envoyee",
            })
        return True

    def action_annuler(self):
        self.write({"etat": "annulee"})
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_locatif.action_report_relance_locataire").report_action(self)

    def date_limite(self):
        self.ensure_one()
        depart = self.date_presentation or self.date
        return depart + timedelta(days=self.delai_jours)
