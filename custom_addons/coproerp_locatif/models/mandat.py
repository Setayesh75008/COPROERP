from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class MandatGestion(models.Model):
    """Mandat de gestion confié par un propriétaire ; son numéro est celui du registre des mandats."""

    _name = "coproerp.locatif.mandat"
    _description = "Mandat de gestion locative"
    _inherit = ["mail.thread"]
    _order = "name desc"

    name = fields.Char(string="N° au registre", readonly=True, copy=False, default="/")
    proprietaire_id = fields.Many2one("res.partner", string="Propriétaire (mandant)", required=True, tracking=True)
    bien_ids = fields.One2many("coproerp.locatif.bien", "mandat_id", string="Biens confiés")
    date_signature = fields.Date(string="Signé le", required=True, default=fields.Date.context_today)
    date_effet = fields.Date(string="Prend effet le", required=True, default=fields.Date.context_today)
    duree_annees = fields.Integer(string="Durée (années)", default=1,
                                  help="Durée initiale ; le mandat est ensuite reconduit tacitement si le contrat "
                                       "le prévoit, dans la limite fixée au mandat.")
    date_echeance = fields.Date(string="Échéance de la période en cours", compute="_compute_date_echeance")
    taux_honoraires = fields.Float(string="Honoraires de gestion (% TTC des sommes encaissées)", digits=(5, 2),
                                   default=7.0, tracking=True)
    depot_conserve = fields.Boolean(
        string="Dépôts de garantie conservés par le gestionnaire", default=True,
        help="Coché : le dépôt de garantie reste sur le compte des mandants jusqu'à sa restitution. "
             "Décoché : il est reversé au propriétaire, qui le restituera.")
    reversement = fields.Selection([("mensuel", "Mensuel"), ("trimestriel", "Trimestriel")],
                                   string="Reversement au propriétaire", default="mensuel", required=True)
    iban_proprietaire = fields.Char(string="IBAN du propriétaire")
    etat = fields.Selection([("brouillon", "En préparation"), ("actif", "En cours"), ("resilie", "Résilié")],
                            string="État", default="brouillon", required=True, tracking=True)
    date_resiliation = fields.Date(string="Résilié le", tracking=True)
    note = fields.Text(string="Clauses particulières")
    nombre_baux = fields.Integer(compute="_compute_nombre_baux")

    @api.depends("date_effet", "duree_annees")
    def _compute_date_echeance(self):
        aujourdhui = fields.Date.context_today(self)
        for mandat in self:
            if not mandat.date_effet or mandat.duree_annees <= 0:
                mandat.date_echeance = False
                continue
            fin = mandat.date_effet + relativedelta(years=mandat.duree_annees, days=-1)
            while fin < aujourdhui:
                fin += relativedelta(years=1)
            mandat.date_echeance = fin

    def _compute_nombre_baux(self):
        for mandat in self:
            mandat.nombre_baux = self.env["coproerp.locatif.bail"].search_count([("mandat_id", "=", mandat.id)])

    @api.constrains("taux_honoraires", "date_signature", "date_effet")
    def _check_mandat(self):
        for mandat in self:
            if not 0 <= mandat.taux_honoraires <= 100:
                raise ValidationError("Le taux des honoraires doit être compris entre 0 et 100 %.")
            if mandat.date_effet < mandat.date_signature:
                raise ValidationError("Le mandat ne peut pas prendre effet avant sa signature.")

    def action_activer(self):
        for mandat in self:
            if mandat.etat != "brouillon":
                continue
            if mandat.name == "/":
                # Numérotation à la signature : le registre des mandats est continu et chronologique.
                mandat.name = self.env["ir.sequence"].next_by_code("coproerp.locatif.mandat") or "/"
            mandat.proprietaire_id.role_bailleur = True
            mandat.etat = "actif"
        return True

    def action_resilier(self):
        for mandat in self:
            baux = self.env["coproerp.locatif.bail"].search([("mandat_id", "=", mandat.id), ("etat", "=", "en_cours")])
            if baux:
                raise UserError("Des baux sont encore en cours sur ce mandat : %s." % ", ".join(baux.mapped("name")))
            mandat.write({"etat": "resilie", "date_resiliation": mandat.date_resiliation
                          or fields.Date.context_today(mandat)})
        return True

    def action_voir_baux(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": "Baux", "res_model": "coproerp.locatif.bail",
                "view_mode": "list,form", "domain": [("mandat_id", "=", self.id)]}

    def unlink(self):
        if any(m.name != "/" for m in self):
            raise UserError("Un mandat inscrit au registre ne peut pas être supprimé : résiliez-le.")
        return super().unlink()
