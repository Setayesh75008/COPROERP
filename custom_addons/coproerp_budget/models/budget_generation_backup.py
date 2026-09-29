from odoo import models, fields, api
from odoo.exceptions import ValidationError


class BudgetAnnuel(models.Model):
    _name = "coproerp.budget.annuel"
    _description = "Budget prévisionnel annuel et fonds de travaux"
    _rec_name = "reference"
    _order = "exercice desc, reference desc"

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

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
    )

    exercice = fields.Integer(
        string="Exercice",
        required=True,
    )

    date_debut = fields.Date(
        string="Début de l'exercice",
        required=True,
    )

    date_fin = fields.Date(
        string="Fin de l'exercice",
        required=True,
    )

    budget_previsionnel = fields.Float(
        string="Budget prévisionnel",
        required=True,
        digits=(16, 2),
    )

    # =========================
    # Fonds de travaux
    # =========================

    ppt_adopte = fields.Boolean(
        string="PPT adopté",
        default=False,
    )

    montant_travaux_ppt = fields.Float(
        string="Montant des travaux prévus au PPT",
        default=0.0,
        digits=(16, 2),
    )

    taux_fonds_travaux = fields.Float(
        string="Taux du fonds travaux (%)",
        default=5.0,
        required=True,
        digits=(16, 4),
    )

    minimum_fonds_5pct = fields.Float(
        string="Minimum 5 % du budget",
        compute="_compute_fonds_travaux",
        store=True,
        digits=(16, 2),
    )

    minimum_fonds_ppt = fields.Float(
        string="Minimum 2,5 % du PPT",
        compute="_compute_fonds_travaux",
        store=True,
        digits=(16, 2),
    )

    minimum_legal_fonds = fields.Float(
        string="Minimum légal",
        compute="_compute_fonds_travaux",
        store=True,
        digits=(16, 2),
    )

    cotisation_annuelle_fonds = fields.Float(
        string="Cotisation annuelle fonds travaux",
        compute="_compute_fonds_travaux",
        store=True,
        digits=(16, 2),
    )

    nombre_appels_fonds = fields.Integer(
        string="Nombre d'appels fonds travaux",
        default=4,
        required=True,
    )

    cotisation_par_appel_fonds = fields.Float(
        string="Cotisation par appel",
        compute="_compute_cotisation_par_appel",
        store=True,
        digits=(16, 2),
    )

    note = fields.Text(
        string="Observations",
    )

    @api.depends(
        "budget_previsionnel",
        "ppt_adopte",
        "montant_travaux_ppt",
        "taux_fonds_travaux",
    )
    def _compute_fonds_travaux(self):
        for budget in self:

            budget.minimum_fonds_5pct = (
                budget.budget_previsionnel * 5.0 / 100.0
            )

            if budget.ppt_adopte:
                budget.minimum_fonds_ppt = (
                    budget.montant_travaux_ppt * 2.5 / 100.0
                )
            else:
                budget.minimum_fonds_ppt = 0.0

            budget.minimum_legal_fonds = max(
                budget.minimum_fonds_5pct,
                budget.minimum_fonds_ppt,
            )

            budget.cotisation_annuelle_fonds = (
                budget.budget_previsionnel
                * budget.taux_fonds_travaux
                / 100.0
            )

    @api.depends(
        "cotisation_annuelle_fonds",
        "nombre_appels_fonds",
    )
    def _compute_cotisation_par_appel(self):
        for budget in self:
            if budget.nombre_appels_fonds:
                budget.cotisation_par_appel_fonds = (
                    budget.cotisation_annuelle_fonds
                    / budget.nombre_appels_fonds
                )
            else:
                budget.cotisation_par_appel_fonds = 0.0

    @api.constrains("budget_previsionnel")
    def _check_budget(self):
        for budget in self:
            if budget.budget_previsionnel <= 0:
                raise ValidationError(
                    "Le budget prévisionnel doit être supérieur à zéro."
                )

    @api.constrains(
        "ppt_adopte",
        "montant_travaux_ppt",
    )
    def _check_ppt(self):
        for budget in self:
            if (
                budget.ppt_adopte
                and budget.montant_travaux_ppt <= 0
            ):
                raise ValidationError(
                    "Lorsque le PPT est adopté, le montant des travaux "
                    "prévus doit être supérieur à zéro."
                )

    @api.constrains("taux_fonds_travaux")
    def _check_taux_fonds_travaux(self):
        for budget in self:
            if budget.taux_fonds_travaux < 5.0:
                raise ValidationError(
                    "Le taux du fonds travaux ne peut pas être inférieur "
                    "à 5 % du budget prévisionnel."
                )

    @api.constrains("nombre_appels_fonds")
    def _check_nombre_appels(self):
        for budget in self:
            if budget.nombre_appels_fonds <= 0:
                raise ValidationError(
                    "Le nombre d'appels du fonds travaux doit être "
                    "supérieur à zéro."
                )

    @api.constrains(
        "date_debut",
        "date_fin",
    )
    def _check_dates(self):
        for budget in self:
            if (
                budget.date_debut
                and budget.date_fin
                and budget.date_fin < budget.date_debut
            ):
                raise ValidationError(
                    "La date de fin doit être postérieure ou égale "
                    "à la date de début."
                )

    @api.constrains(
        "copropriete_id",
        "exercice",
    )
    def _check_unique_exercice(self):
        for budget in self:
            duplicate = self.search_count([
                ("id", "!=", budget.id),
                ("copropriete_id", "=", budget.copropriete_id.id),
                ("exercice", "=", budget.exercice),
            ])

            if duplicate:
                raise ValidationError(
                    "Un seul budget annuel peut être créé pour "
                    "une copropriété et un même exercice."
                )

    @api.constrains(
        "taux_fonds_travaux",
        "budget_previsionnel",
        "ppt_adopte",
        "montant_travaux_ppt",
    )
    def _check_minimum_fonds(self):
        for budget in self:

            cotisation = (
                budget.budget_previsionnel
                * budget.taux_fonds_travaux
                / 100.0
            )

            minimum_legal = max(
                budget.budget_previsionnel * 5.0 / 100.0,
                (
                    budget.montant_travaux_ppt * 2.5 / 100.0
                    if budget.ppt_adopte
                    else 0.0
                ),
            )

            if cotisation < minimum_legal:
                raise ValidationError(
                    "La cotisation annuelle du fonds travaux ne "
                    "respecte pas le minimum légal applicable."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("reference", "/") == "/":
                vals["reference"] = (
                    self.env["ir.sequence"].next_by_code(
                        "coproerp.budget.annuel"
                    )
                    or "/"
                )

        return super().create(vals_list)