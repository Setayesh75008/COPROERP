from odoo import api, fields, models

TYPES_BIEN = [
    ("appartement", "Appartement"),
    ("maison", "Maison"),
    ("studio", "Studio / chambre"),
    ("local_commercial", "Local commercial"),
    ("bureau", "Bureau / local professionnel"),
    ("parking", "Parking / garage"),
    ("cave", "Cave / box"),
    ("autre", "Autre"),
]


class BienLoue(models.Model):
    """Bien confié en gestion (un appartement, un local, un parking…)."""

    _name = "coproerp.locatif.bien"
    _description = "Bien en gestion locative"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(string="Désignation", required=True)
    type_bien = fields.Selection(TYPES_BIEN, string="Type", required=True, default="appartement")
    mandat_id = fields.Many2one("coproerp.locatif.mandat", string="Mandat de gestion", required=True,
                                domain="[('etat', '!=', 'resilie')]", tracking=True)
    proprietaire_id = fields.Many2one(related="mandat_id.proprietaire_id", store=True, string="Propriétaire")
    street = fields.Char(string="Adresse", required=True)
    street2 = fields.Char(string="Complément (étage, porte)")
    zip = fields.Char(string="Code postal", required=True)
    city = fields.Char(string="Ville", required=True)
    surface = fields.Float(string="Surface habitable (m²)", digits=(8, 2))
    nombre_pieces = fields.Integer(string="Pièces principales")
    meuble = fields.Boolean(string="Meublé")
    lot_id = fields.Many2one("coproerp.lot", string="Lot de copropriété",
                             help="Si le bien est un lot d'une copropriété, pour retrouver ses charges.")
    zone_tendue = fields.Boolean(string="Zone tendue",
                                 help="Préavis du locataire réduit à un mois pour un logement non meublé ; "
                                      "encadrement de l'évolution du loyer à la relocation.")
    classe_energie = fields.Selection([(x, x) for x in "ABCDEFG"], string="Classe énergie (DPE)")
    bail_ids = fields.One2many("coproerp.locatif.bail", "bien_id", string="Baux")
    bail_en_cours_id = fields.Many2one("coproerp.locatif.bail", string="Bail en cours",
                                       compute="_compute_bail_en_cours")
    occupe = fields.Boolean(string="Loué", compute="_compute_bail_en_cours")

    @api.depends("bail_ids.etat")
    def _compute_bail_en_cours(self):
        for bien in self:
            bail = bien.bail_ids.filtered(lambda b: b.etat == "en_cours")[:1]
            bien.bail_en_cours_id = bail
            bien.occupe = bool(bail)

    def adresse_complete(self):
        self.ensure_one()
        return ", ".join(x for x in (self.street, self.street2, "%s %s" % (self.zip or "", self.city or "")) if x)
