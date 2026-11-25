from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

ETATS = [("neuf", "Neuf"), ("bon", "Bon état"), ("usage", "État d'usage"), ("mauvais", "Mauvais état"),
         ("hs", "Hors d'usage")]
RANG = {"neuf": 5, "bon": 4, "usage": 3, "mauvais": 2, "hs": 1}

ELEMENTS_COMMUNS = ["Sol", "Murs", "Plafond", "Porte et serrure", "Fenêtres et volets", "Prises et interrupteurs",
                    "Éclairage", "Chauffage"]
PIECES_TYPES = [
    ("Entrée", []),
    ("Séjour", []),
    ("Cuisine", ["Évier et robinetterie", "Plan de travail", "Placards", "Plaques et four", "Hotte"]),
    ("Chambre", ["Placard"]),
    ("Salle de bains", ["Baignoire ou douche", "Lavabo et robinetterie", "Faïence", "Ventilation"]),
    ("WC", ["Cuvette et chasse d'eau"]),
]


class EtatDesLieux(models.Model):
    """État des lieux contradictoire d'entrée ou de sortie (art. 3-2 de la loi du 6 juillet 1989)."""

    _name = "coproerp.locatif.etat_lieux"
    _description = "État des lieux"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    bail_id = fields.Many2one("coproerp.locatif.bail", string="Bail", required=True, index=True, ondelete="cascade",
                              domain="[('etat', '!=', 'brouillon')]")
    type_edl = fields.Selection([("entree", "Entrée"), ("sortie", "Sortie")], string="État des lieux",
                                required=True, default="entree")
    date = fields.Date(string="Établi le", required=True, default=fields.Date.context_today)
    bien_id = fields.Many2one(related="bail_id.bien_id", store=True, string="Bien")
    locataire_id = fields.Many2one(related="bail_id.locataire_id", store=True, string="Locataire")
    proprietaire_id = fields.Many2one(related="bail_id.proprietaire_id", store=True, string="Propriétaire")
    representant = fields.Char(string="Pour le bailleur", default=lambda self: self.env.company.name)
    presents = fields.Char(string="Locataire(s) présent(s) ou représenté(s)")
    entree_id = fields.Many2one("coproerp.locatif.etat_lieux", string="État des lieux d'entrée",
                                compute="_compute_entree", store=True, readonly=False)
    eau_froide = fields.Char(string="Eau froide (m³)")
    eau_chaude = fields.Char(string="Eau chaude (m³)")
    electricite = fields.Char(string="Électricité (kWh)")
    gaz = fields.Char(string="Gaz (m³ ou kWh)")
    chauffage = fields.Char(string="Chauffage et eau chaude", help="Individuel ou collectif, énergie, appareil.")
    cles = fields.Text(string="Clés et badges remis", help="Nombre et nature : clés de l'appartement, boîte aux "
                                                          "lettres, cave, badges, télécommandes…")
    ligne_ids = fields.One2many("coproerp.locatif.etat_lieux.ligne", "etat_lieux_id", string="Pièces et éléments")
    observations = fields.Text(string="Observations")
    nombre_degradations = fields.Integer(string="Dégradations constatées", compute="_compute_degradations",
                                         store=True)
    conforme = fields.Boolean(string="Conforme à l'entrée", compute="_compute_degradations", store=True,
                              help="Aucun élément en moins bon état qu'à l'entrée.")
    etat = fields.Selection([("brouillon", "En préparation"), ("signe", "Signé")], string="État",
                            default="brouillon", required=True, tracking=True)

    @api.depends("bail_id", "type_edl")
    def _compute_entree(self):
        for edl in self:
            if edl.type_edl == "sortie" and edl.bail_id and not edl.entree_id:
                edl.entree_id = self.search([("bail_id", "=", edl.bail_id.id), ("type_edl", "=", "entree"),
                                             ("etat", "=", "signe")], order="date desc", limit=1)
            else:
                edl.entree_id = edl.entree_id

    @api.depends("type_edl", "ligne_ids.degradation")
    def _compute_degradations(self):
        for edl in self:
            nombre = len(edl.ligne_ids.filtered("degradation")) if edl.type_edl == "sortie" else 0
            edl.nombre_degradations = nombre
            edl.conforme = edl.type_edl == "sortie" and not nombre

    @api.constrains("bail_id", "type_edl", "etat")
    def _check_unique(self):
        for edl in self.filtered(lambda e: e.etat == "signe"):
            if self.search_count([("bail_id", "=", edl.bail_id.id), ("type_edl", "=", edl.type_edl),
                                  ("etat", "=", "signe"), ("id", "!=", edl.id)]):
                raise ValidationError("Un état des lieux %s est déjà signé pour le bail %s."
                                      % ("d'entrée" if edl.type_edl == "entree" else "de sortie", edl.bail_id.name))

    # ------------------------------------------------------------------
    def action_pieces_types(self):
        for edl in self.filtered(lambda e: e.etat == "brouillon"):
            if edl.ligne_ids:
                raise UserError("L'état des lieux contient déjà des pièces.")
            lignes, sequence = [], 0
            for piece, propres in PIECES_TYPES:
                for element in ELEMENTS_COMMUNS + propres:
                    sequence += 1
                    lignes.append((0, 0, {"sequence": sequence, "piece": piece, "element": element}))
            edl.ligne_ids = lignes
        return True

    def action_reprendre_entree(self):
        """Recopie les pièces de l'état des lieux d'entrée, avec leur état d'alors."""
        for edl in self.filtered(lambda e: e.etat == "brouillon" and e.type_edl == "sortie"):
            if not edl.entree_id:
                raise UserError("Aucun état des lieux d'entrée signé n'est rattaché à ce bail.")
            edl.ligne_ids.unlink()
            edl.ligne_ids = [(0, 0, {"sequence": l.sequence, "piece": l.piece, "element": l.element,
                                     "etat": l.etat, "etat_entree": l.etat, "observations_entree": l.observations})
                             for l in edl.entree_id.ligne_ids]
            for releve in ("eau_froide", "eau_chaude", "electricite", "gaz", "chauffage", "cles"):
                if not edl[releve]:
                    edl[releve] = edl.entree_id[releve]
        return True

    def action_signer(self):
        for edl in self.filtered(lambda e: e.etat == "brouillon"):
            if not edl.ligne_ids:
                raise UserError("Décrivez les pièces avant de faire signer l'état des lieux.")
            if edl.ligne_ids.filtered(lambda l: not l.etat):
                raise UserError("Indiquez l'état de chaque élément.")
            if edl.name == "/":
                edl.name = self.env["ir.sequence"].next_by_code("coproerp.locatif.etat_lieux") or "/"
            edl.etat = "signe"
        return True

    def action_remettre_brouillon(self):
        self.write({"etat": "brouillon"})
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_locatif_sortie.action_report_etat_lieux").report_action(self)

    def pieces(self):
        """Lignes regroupées par pièce, dans l'ordre, pour l'impression."""
        self.ensure_one()
        groupes = []
        for ligne in self.ligne_ids.sorted(lambda l: (l.sequence, l.id)):
            if not groupes or groupes[-1][0] != ligne.piece:
                groupes.append((ligne.piece, []))
            groupes[-1][1].append(ligne)
        return groupes


class EtatDesLieuxLigne(models.Model):
    _name = "coproerp.locatif.etat_lieux.ligne"
    _description = "Élément d'un état des lieux"
    _order = "sequence, id"

    etat_lieux_id = fields.Many2one("coproerp.locatif.etat_lieux", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    piece = fields.Char(string="Pièce", required=True)
    element = fields.Char(string="Élément", required=True)
    etat = fields.Selection(ETATS, string="État")
    observations = fields.Char(string="Observations")
    etat_entree = fields.Selection(ETATS, string="État à l'entrée", readonly=True)
    observations_entree = fields.Char(string="Observations à l'entrée", readonly=True)
    degradation = fields.Boolean(string="Dégradation", compute="_compute_degradation", store=True)

    @api.depends("etat", "etat_entree")
    def _compute_degradation(self):
        for ligne in self:
            ligne.degradation = bool(ligne.etat and ligne.etat_entree and RANG[ligne.etat] < RANG[ligne.etat_entree])

    def libelle(self, etat):
        return dict(ETATS).get(etat, "")
