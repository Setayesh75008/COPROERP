from datetime import timedelta

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

    def action_generer_appels_fonds_travaux(self):
        """Génère les appels de fonds travaux pour le budget sélectionné.

        Règle de génération :
        - un seul appel par copropriétaire et par période ;
        - tous les lots appartenant à ce copropriétaire sont regroupés
          dans ce même appel ;
        - chaque lot reçoit son propre groupe et son propre poste
          « Fonds obligatoire travaux ».

        Ainsi, un copropriétaire possédant deux lots et un budget comportant
        quatre appels reçoit exactement quatre appels de fonds, et non huit.

        Sécurité : si un lot possède plusieurs propriétaires, la génération
        est interrompue car le modèle actuel ne permet pas encore de porter
        la quotité de propriété de chaque copropriétaire dans
        proprietaire_ids.
        """
        self.ensure_one()

        if not self.active:
            raise ValidationError(
                "Le budget annuel doit être actif pour générer les appels de fonds travaux."
            )
        if not self.copropriete_id:
            raise ValidationError(
                "Le budget doit être rattaché à une copropriété."
            )
        if not self.date_debut or not self.date_fin:
            raise ValidationError(
                "Les dates de début et de fin de l'exercice sont obligatoires."
            )
        if self.date_fin < self.date_debut:
            raise ValidationError(
                "La date de fin doit être postérieure ou égale à la date de début."
            )
        if self.nombre_appels_fonds <= 0:
            raise ValidationError(
                "Le nombre d'appels du fonds travaux doit être supérieur à zéro."
            )
        if self.cotisation_par_appel_fonds <= 0:
            raise ValidationError(
                "La cotisation par appel du fonds travaux doit être supérieure à zéro."
            )

        appel_model = self.env["coproerp.appel.charge"]
        lot_model = self.env["coproerp.lot"]
        repartition_model = self.env["coproerp.repartition"]

        repartitions = repartition_model.search([
            ("copropriete_id", "=", self.copropriete_id.id),
            ("type_repartition", "=", "fonds_travaux"),
            ("active", "=", True),
        ])
        if not repartitions:
            raise ValidationError(
                "Aucune clé de répartition active de type « Fonds obligatoire travaux » "
                "n'est définie pour cette copropriété."
            )
        if len(repartitions) > 1:
            raise ValidationError(
                "Plusieurs clés de répartition actives de type « Fonds obligatoire travaux » "
                "existent pour cette copropriété. Une seule doit être active avant la génération."
            )
        repartition_fonds = repartitions[0]

        lots = lot_model.search([
            ("copropriete_id", "=", self.copropriete_id.id),
            ("proprietaire_ids", "!=", False),
        ], order="numero, id")
        if not lots:
            raise ValidationError(
                "Aucun lot avec copropriétaire n'est enregistré dans cette copropriété."
            )

        lots_multi_proprietaires = lots.filtered(
            lambda lot: len(lot.proprietaire_ids) > 1
        )
        if lots_multi_proprietaires:
            numeros = ", ".join(lots_multi_proprietaires.mapped("numero"))
            raise ValidationError(
                "La génération automatique est interrompue car les lots suivants "
                "ont plusieurs copropriétaires : %s. Le modèle actuel ne permet "
                "pas encore de répartir automatiquement la quote-part entre "
                "copropriétaires indivis." % numeros
            )

        coproprietaires = lots.mapped("proprietaire_ids")

        coproprietaires_sans_role = coproprietaires.filtered(
            lambda personne: not personne.role_coproprietaire
        )
        if coproprietaires_sans_role:
            noms = ", ".join(coproprietaires_sans_role.mapped("name"))
            raise ValidationError(
                "Les personnes suivantes sont propriétaires d'un lot mais ne sont "
                "pas marquées comme copropriétaires : %s." % noms
            )

        # IMPORTANT :
        # On regroupe d'abord les lots par copropriétaire.
        # Cela garantit qu'un copropriétaire possédant plusieurs lots
        # reçoit un seul appel par période, contenant tous ses lots.
        lots_par_coproprietaire = {}
        for coproprietaire in coproprietaires.sorted(
            key=lambda personne: (personne.name or "").lower()
        ):
            lots_coproprietaire = lots.filtered(
                lambda lot: coproprietaire in lot.proprietaire_ids
            )
            if lots_coproprietaire:
                lots_par_coproprietaire[coproprietaire.id] = (
                    coproprietaire,
                    lots_coproprietaire,
                )

        date_debut = fields.Date.to_date(self.date_debut)
        date_fin = fields.Date.to_date(self.date_fin)
        total_jours = (date_fin - date_debut).days + 1

        if self.nombre_appels_fonds > total_jours:
            raise ValidationError(
                "Le nombre d'appels du fonds travaux ne peut pas dépasser "
                "le nombre de jours de l'exercice."
            )

        # Première boucle : les périodes du budget.
        # Deuxième boucle : les copropriétaires.
        # Il ne peut donc y avoir qu'un appel par copropriétaire et par période.
        for numero_appel in range(1, self.nombre_appels_fonds + 1):
            debut = date_debut + timedelta(
                days=(
                    total_jours * (numero_appel - 1)
                ) // self.nombre_appels_fonds
            )
            fin = date_debut + timedelta(
                days=(
                    total_jours * numero_appel
                ) // self.nombre_appels_fonds - 1
            )

            for coproprietaire_id, data in lots_par_coproprietaire.items():
                coproprietaire, lots_coproprietaire = data

                appel_existant = appel_model.search([
                    ("budget_id", "=", self.id),
                    ("personne_id", "=", coproprietaire_id),
                    ("type_appel", "=", "fonds_travaux"),
                    ("numero_appel_budget", "=", numero_appel),
                ], limit=1)

                if appel_existant:
                    continue

                date_echeance = min(
                    debut + timedelta(days=15),
                    fin,
                )

                appel = appel_model.create({
                    "personne_id": coproprietaire_id,
                    "copropriete_id": self.copropriete_id.id,
                    "budget_id": self.id,
                    "type_appel": "fonds_travaux",
                    "numero_appel_budget": numero_appel,
                    "date_appel": debut,
                    "date_echeance": date_echeance,
                    "date_debut_periode": debut,
                    "date_fin_periode": fin,
                    "note": (
                        "Appel généré automatiquement à partir du budget %s. "
                        "Appel n° %s/%s." % (
                            self.reference,
                            numero_appel,
                            self.nombre_appels_fonds,
                        )
                    ),
                })

                # Tous les lots de ce copropriétaire sont ajoutés
                # au même appel.
                for lot in lots_coproprietaire:
                    groupe = self.env["coproerp.appel.charge.groupe"].create({
                        "appel_id": appel.id,
                        "lot_id": lot.id,
                    })

                    self.env["coproerp.appel.charge.poste"].create({
                        "groupe_id": groupe.id,
                        "type_poste": "fonds_travaux",
                        "designation": "Fonds obligatoire travaux",
                        "repartition_id": repartition_fonds.id,
                        "total_a_repartir": self.cotisation_par_appel_fonds,
                        "sequence": 10,
                    })

        return {
            "type": "ir.actions.act_window",
            "name": "Appels de fonds travaux générés",
            "res_model": "coproerp.appel.charge",
            "view_mode": "list,form",
            "domain": [
                ("budget_id", "=", self.id),
                ("type_appel", "=", "fonds_travaux"),
            ],
            "context": {
                "default_budget_id": self.id,
                "default_copropriete_id": self.copropriete_id.id,
                "default_type_appel": "fonds_travaux",
            },
        }


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








