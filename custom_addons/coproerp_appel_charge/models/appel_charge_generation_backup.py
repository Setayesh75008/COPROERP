from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AppelCharge(models.Model):
    _name = "coproerp.appel.charge"
    _description = "Appel de fonds"
    _rec_name = "reference"
    _order = "date_echeance desc, reference desc"

    active = fields.Boolean(
        string="Actif",
        default=True,
    )

    reference = fields.Char(
        string="Référence",
        readonly=True,
        copy=False,
        default="/",
    )

    personne_id = fields.Many2one(
        "res.partner",
        string="Copropriétaire",
        required=True,
        domain="[('role_coproprietaire', '=', True)]",
        ondelete="cascade",
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
    )

    budget_id = fields.Many2one(
        "coproerp.budget.annuel",
        string="Budget annuel",
        domain="[('copropriete_id', '=', copropriete_id)]",
        ondelete="restrict",
    )

    montant_fonds_travaux_appel = fields.Float(
        string="Montant du fonds travaux par appel",
        related="budget_id.cotisation_par_appel_fonds",
        readonly=True,
        digits=(16, 2),
    )

    type_appel = fields.Selection(
        [
            (
                "budget_courant",
                "Budget courant",
            ),
            (
                "fonds_travaux",
                "Fonds obligatoire travaux",
            ),
            (
                "hors_budget",
                "Hors budget",
            ),
            (
                "avance",
                "Avance",
            ),
            (
                "autre",
                "Autre",
            ),
        ],
        string="Type d'appel",
        required=True,
        default="budget_courant",
    )

    date_appel = fields.Date(
        string="Date de l'appel",
        default=fields.Date.context_today,
        required=True,
    )

    date_echeance = fields.Date(
        string="Date d'échéance",
        required=True,
    )

    date_debut_periode = fields.Date(
        string="Début de période",
    )

    date_fin_periode = fields.Date(
        string="Fin de période",
    )

    groupe_ids = fields.One2many(
        "coproerp.appel.charge.groupe",
        "appel_id",
        string="Détail par lot",
    )

    total_appel = fields.Float(
        string="Total de l'appel",
        compute="_compute_total_appel",
        store=True,
        digits=(16, 2),
    )

    note = fields.Text(
        string="Observations",
    )

    @api.depends("groupe_ids.total_groupe")
    def _compute_total_appel(self):
        for appel in self:
            appel.total_appel = sum(
                appel.groupe_ids.mapped("total_groupe")
            )

    @api.constrains(
        "date_debut_periode",
        "date_fin_periode",
    )
    def _check_periode(self):
        for appel in self:
            if (
                appel.date_debut_periode
                and appel.date_fin_periode
                and appel.date_fin_periode < appel.date_debut_periode
            ):
                raise ValidationError(
                    "La date de fin de période doit être postérieure "
                    "ou égale à la date de début."
                )

    @api.constrains(
        "date_appel",
        "date_echeance",
    )
    def _check_echeance(self):
        for appel in self:
            if (
                appel.date_appel
                and appel.date_echeance
                and appel.date_echeance < appel.date_appel
            ):
                raise ValidationError(
                    "La date d'échéance ne peut pas être antérieure "
                    "à la date de l'appel."
                )

    @api.onchange("type_appel")
    def _onchange_type_appel(self):
        for appel in self:
            if appel.type_appel != "fonds_travaux":
                appel.budget_id = False

    @api.constrains(
        "type_appel",
        "budget_id",
        "copropriete_id",
    )
    def _check_budget_fonds_travaux(self):
        for appel in self:

            if appel.type_appel == "fonds_travaux":

                if not appel.budget_id:
                    raise ValidationError(
                        "Un appel de type Fonds obligatoire travaux doit "
                        "être rattaché à un budget annuel."
                    )

                if (
                    appel.budget_id.copropriete_id
                    and appel.budget_id.copropriete_id != appel.copropriete_id
                ):
                    raise ValidationError(
                        "Le budget annuel doit appartenir à la même "
                        "copropriété que l'appel de fonds."
                    )

                if not appel.budget_id.active:
                    raise ValidationError(
                        "Le budget annuel sélectionné est inactif."
                    )

            elif appel.budget_id:

                raise ValidationError(
                    "Le budget annuel ne peut être renseigné que pour un "
                    "appel de type Fonds obligatoire travaux."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("reference", "/") == "/":
                vals["reference"] = (
                    self.env["ir.sequence"].next_by_code(
                        "coproerp.appel.charge"
                    )
                    or "/"
                )

        return super().create(vals_list)


class AppelChargeGroupe(models.Model):
    _name = "coproerp.appel.charge.groupe"
    _description = "Détail d'un lot dans un appel de fonds"
    _order = "lot_id"

    appel_id = fields.Many2one(
        "coproerp.appel.charge",
        string="Appel de fonds",
        required=True,
        ondelete="cascade",
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        related="appel_id.copropriete_id",
        store=True,
        readonly=True,
    )

    lot_id = fields.Many2one(
        "coproerp.lot",
        string="Lot",
        required=True,
        ondelete="cascade",
        domain="[('copropriete_id', '=', copropriete_id)]",
    )

    lot_numero = fields.Char(
        string="N° de lot",
        related="lot_id.numero",
        store=True,
        readonly=True,
    )

    lot_designation = fields.Char(
        string="Désignation",
        related="lot_id.designation",
        store=True,
        readonly=True,
    )

    poste_ids = fields.One2many(
        "coproerp.appel.charge.poste",
        "groupe_id",
        string="Postes de dépenses",
    )

    total_groupe = fields.Float(
        string="Total du lot",
        compute="_compute_total_groupe",
        store=True,
        digits=(16, 2),
    )

    @api.depends("poste_ids.montant_appel")
    def _compute_total_groupe(self):
        for groupe in self:
            groupe.total_groupe = sum(
                groupe.poste_ids.mapped("montant_appel")
            )

    @api.constrains(
        "lot_id",
        "appel_id",
    )
    def _check_lot_copropriete(self):
        for groupe in self:
            if (
                groupe.lot_id
                and groupe.copropriete_id
                and groupe.lot_id.copropriete_id
                != groupe.copropriete_id
            ):
                raise ValidationError(
                    "Le lot sélectionné doit appartenir à la même "
                    "copropriété que l'appel de fonds."
                )

    def action_open_groupe(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Détail par lot",
            "res_model": "coproerp.appel.charge.groupe",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "coproerp_appel_charge.view_appel_charge_groupe_form"
                    ).id,
                    "form",
                )
            ],
            "res_id": self.id,
            "target": "current",
        }


class AppelChargePoste(models.Model):
    _name = "coproerp.appel.charge.poste"
    _description = "Poste de dépense d'un appel de fonds"
    _order = "sequence, id"

    groupe_id = fields.Many2one(
        "coproerp.appel.charge.groupe",
        string="Détail par lot",
        required=True,
        ondelete="cascade",
    )

    appel_id = fields.Many2one(
        "coproerp.appel.charge",
        string="Appel de fonds",
        related="groupe_id.appel_id",
        store=True,
        readonly=True,
    )

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        related="groupe_id.copropriete_id",
        store=True,
        readonly=True,
    )

    lot_id = fields.Many2one(
        "coproerp.lot",
        string="Lot",
        related="groupe_id.lot_id",
        store=True,
        readonly=True,
    )

    type_poste = fields.Selection(
        [
            (
                "charges_generales",
                "Charges communes générales",
            ),
            (
                "chauffage",
                "Charges chauffage",
            ),
            (
                "eau_chaude",
                "Charges eau chaude",
            ),
            (
                "ascenseur_escalier",
                "Charges ascenseur / escalier",
            ),
            (
                "fonds_travaux",
                "Fonds obligatoire travaux",
            ),
            (
                "autre",
                "Autre",
            ),
        ],
        string="Type de poste",
        required=True,
        default="charges_generales",
    )

    designation = fields.Char(
        string="Désignation",
        required=True,
    )

    repartition_id = fields.Many2one(
        "coproerp.repartition",
        string="Clé de répartition",
        required=True,
        ondelete="restrict",
    )

    allowed_repartition_ids = fields.Many2many(
        "coproerp.repartition",
        string="Clés de répartition autorisées",
        compute="_compute_allowed_repartition_ids",
    )

    total_a_repartir = fields.Float(
        string="Total à répartir",
        required=True,
        default=0.0,
        digits=(16, 2),
    )

    nombre_total_parts = fields.Integer(
        string="Nombre total de parts",
        compute="_compute_parts_repartition",
        store=True,
        readonly=True,
    )

    nombre_parts_lot = fields.Integer(
        string="Nombre de parts du lot",
        compute="_compute_parts_repartition",
        store=True,
        readonly=True,
    )

    pourcentage = fields.Float(
        string="Quote-part (%)",
        compute="_compute_pourcentage",
        store=True,
        digits=(16, 4),
    )

    montant_appel = fields.Float(
        string="Montant de l'appel",
        compute="_compute_montant_appel",
        store=True,
        digits=(16, 2),
    )

    sequence = fields.Integer(
        string="Séquence",
        default=10,
    )

    @api.depends(
        "copropriete_id",
        "type_poste",
    )
    def _compute_allowed_repartition_ids(self):
        repartition_model = self.env[
            "coproerp.repartition"
        ]

        for poste in self:
            poste.allowed_repartition_ids = False

            if (
                not poste.copropriete_id
                or not poste.type_poste
            ):
                continue

            repartitions = repartition_model.search(
                [
                    (
                        "copropriete_id",
                        "=",
                        poste.copropriete_id.id,
                    ),
                    (
                        "type_repartition",
                        "=",
                        poste.type_poste,
                    ),
                ]
            )

            poste.allowed_repartition_ids = repartitions

    @api.depends(
        "repartition_id.total_tantiemes",
        "repartition_id.line_ids.tantiemes",
        "lot_id",
    )
    def _compute_parts_repartition(self):
        repartition_lot_model = self.env[
            "coproerp.repartition.lot"
        ]

        for poste in self:
            poste.nombre_total_parts = 0
            poste.nombre_parts_lot = 0

            if (
                not poste.repartition_id
                or not poste.lot_id
            ):
                continue

            poste.nombre_total_parts = (
                poste.repartition_id.total_tantiemes
            )

            ligne_repartition = repartition_lot_model.search(
                [
                    (
                        "repartition_id",
                        "=",
                        poste.repartition_id.id,
                    ),
                    (
                        "lot_id",
                        "=",
                        poste.lot_id.id,
                    ),
                ],
                limit=1,
            )

            if ligne_repartition:
                poste.nombre_parts_lot = (
                    ligne_repartition.tantiemes
                )

    @api.depends(
        "nombre_parts_lot",
        "nombre_total_parts",
    )
    def _compute_pourcentage(self):
        for poste in self:
            if poste.nombre_total_parts:
                poste.pourcentage = (
                    poste.nombre_parts_lot
                    / poste.nombre_total_parts
                ) * 100
            else:
                poste.pourcentage = 0.0

    @api.depends(
        "total_a_repartir",
        "nombre_parts_lot",
        "nombre_total_parts",
    )
    def _compute_montant_appel(self):
        for poste in self:
            if poste.nombre_total_parts:
                poste.montant_appel = (
                    poste.total_a_repartir
                    * poste.nombre_parts_lot
                    / poste.nombre_total_parts
                )
            else:
                poste.montant_appel = 0.0

    @api.onchange("type_poste", "groupe_id")
    def _onchange_fonds_travaux(self):
        for poste in self:

            if (
                poste.type_poste == "fonds_travaux"
                and poste.appel_id
                and poste.appel_id.budget_id
            ):
                poste.designation = (
                    poste.designation
                    or "Fonds obligatoire travaux"
                )

                poste.total_a_repartir = (
                    poste.appel_id.budget_id.cotisation_par_appel_fonds
                )

    @api.constrains(
        "type_poste",
        "total_a_repartir",
        "appel_id",
    )
    def _check_fonds_travaux(self):
        for poste in self:

            if not poste.appel_id:
                continue

            if poste.appel_id.type_appel == "fonds_travaux":

                if poste.type_poste != "fonds_travaux":
                    raise ValidationError(
                        "Un appel de fonds travaux ne peut contenir que des "
                        "postes de type Fonds obligatoire travaux."
                    )

            if poste.type_poste == "fonds_travaux":

                if poste.appel_id.type_appel != "fonds_travaux":
                    raise ValidationError(
                        "Un poste Fonds obligatoire travaux doit être "
                        "rattaché à un appel de type Fonds obligatoire travaux."
                    )

                if not poste.appel_id.budget_id:
                    raise ValidationError(
                        "Le poste Fonds obligatoire travaux nécessite "
                        "un budget annuel."
                    )

                montant_attendu = (
                    poste.appel_id.budget_id.cotisation_par_appel_fonds
                )

                if abs(
                    poste.total_a_repartir - montant_attendu
                ) > 0.01:
                    raise ValidationError(
                        "Le total à répartir du poste Fonds obligatoire "
                        "travaux doit correspondre au montant par appel "
                        "du budget annuel."
                    )

    @api.constrains(
        "repartition_id",
        "type_poste",
        "copropriete_id",
    )
    def _check_type_repartition(self):
        for poste in self:
            if (
                poste.repartition_id
                and poste.copropriete_id
                and poste.repartition_id.copropriete_id
                != poste.copropriete_id
            ):
                raise ValidationError(
                    "La clé de répartition doit appartenir à la "
                    "même copropriété que le poste de dépense."
                )

            if (
                poste.repartition_id
                and poste.type_poste
                and poste.type_poste
                != poste.repartition_id.type_repartition
                and poste.type_poste != "autre"
                and poste.repartition_id.type_repartition != "autre"
            ):
                raise ValidationError(
                    "Le type du poste de dépense doit correspondre "
                    "au type de la clé de répartition."
                )

    @api.constrains(
        "total_a_repartir",
        "nombre_total_parts",
        "nombre_parts_lot",
    )
    def _check_valeurs(self):
        for poste in self:
            if poste.total_a_repartir < 0:
                raise ValidationError(
                    "Le total à répartir ne peut pas être négatif."
                )

            if poste.nombre_total_parts < 0:
                raise ValidationError(
                    "Le nombre total de parts ne peut pas être négatif."
                )

            if poste.nombre_parts_lot < 0:
                raise ValidationError(
                    "Le nombre de parts du lot ne peut pas être négatif."
                )

            if (
                poste.nombre_total_parts
                and poste.nombre_parts_lot > poste.nombre_total_parts
            ):
                raise ValidationError(
                    "Le nombre de parts du lot ne peut pas être "
                    "supérieur au nombre total de parts."
                )
