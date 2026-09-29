from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round

TYPES_CLE_BUDGET = ("charges_generales", "chauffage", "eau_chaude", "ascenseur_escalier", "autre")


class BudgetLigne(models.Model):
    _name = "coproerp.budget.ligne"
    _description = "Ligne du budget prévisionnel (par clé de répartition)"
    _order = "sequence, id"

    budget_id = fields.Many2one(
        "coproerp.budget.annuel", required=True, ondelete="cascade", index=True
    )
    copropriete_id = fields.Many2one(related="budget_id.copropriete_id", store=True)
    sequence = fields.Integer(default=10)
    repartition_id = fields.Many2one(
        "coproerp.repartition",
        string="Clé de répartition",
        required=True,
        ondelete="restrict",
        domain="[('copropriete_id', '=', copropriete_id), "
        "('type_repartition', 'in', %s)]" % str(list(TYPES_CLE_BUDGET)),
    )
    designation = fields.Char(
        string="Libellé sur l'avis",
        help="Par défaut, le nom de la clé (ex. : CHARGES COMMUNES GÉNÉRALES).",
    )
    montant_annuel = fields.Float(string="Montant annuel", digits=(16, 2), required=True)
    montant_par_appel = fields.Float(
        string="Montant par appel",
        compute="_compute_montant_par_appel",
        digits=(16, 2),
    )

    @api.depends("montant_annuel", "budget_id.nombre_appels_budget")
    def _compute_montant_par_appel(self):
        for ligne in self:
            nombre = ligne.budget_id.nombre_appels_budget or 1
            ligne.montant_par_appel = float_round(
                ligne.montant_annuel / nombre, precision_digits=2
            )

    @api.onchange("repartition_id")
    def _onchange_repartition_id(self):
        if self.repartition_id and not self.designation:
            self.designation = (self.repartition_id.name or "").upper()

    @api.constrains("montant_annuel")
    def _check_montant(self):
        for ligne in self:
            if ligne.montant_annuel < 0:
                raise ValidationError("Le montant d'une ligne budgétaire ne peut pas être négatif.")

    def _libelle(self):
        self.ensure_one()
        return self.designation or (self.repartition_id.name or "").upper()


class BudgetAnnuel(models.Model):
    _inherit = "coproerp.budget.annuel"

    ligne_ids = fields.One2many(
        "coproerp.budget.ligne", "budget_id", string="Répartition du budget par clé"
    )
    total_lignes = fields.Float(
        string="Total ventilé",
        compute="_compute_total_lignes",
        digits=(16, 2),
    )
    ecart_ventilation = fields.Float(
        string="Reste à ventiler",
        compute="_compute_total_lignes",
        digits=(16, 2),
    )
    nombre_appels_budget = fields.Integer(
        string="Nombre d'appels du budget courant",
        default=4,
        required=True,
        help="4 = un appel par trimestre, exigible le 1er jour du trimestre "
        "(art. 14-1 de la loi du 10 juillet 1965).",
    )
    delai_edition_jours = fields.Integer(
        string="Édition des avis (jours avant l'échéance)",
        default=15,
        required=True,
    )
    repartition_fonds_travaux_id = fields.Many2one(
        "coproerp.repartition",
        string="Clé d'appel du fonds travaux",
        domain="[('copropriete_id', '=', copropriete_id)]",
        help="Clé selon laquelle le fonds travaux est appelé (souvent les charges "
        "communes générales). Si vide : la clé de type « Fonds obligatoire travaux ».",
    )
    date_premier_appel_fonds = fields.Date(
        string="Premier appel du fonds travaux",
        help="Si le fonds travaux n'est pas appelé sur les mêmes dates que "
        "l'exercice (ex. : voté en AG de mai, premier appel au 1er juillet). "
        "Si vide : début de l'exercice.",
    )
    appel_budget_ids = fields.One2many(
        "coproerp.appel.charge", "budget_origine_id", string="Appels du budget courant"
    )
    appel_budget_count = fields.Integer(compute="_compute_appel_counts")
    appel_fonds_count = fields.Integer(compute="_compute_appel_counts")

    @api.depends("ligne_ids.montant_annuel", "budget_previsionnel")
    def _compute_total_lignes(self):
        for budget in self:
            budget.total_lignes = sum(budget.ligne_ids.mapped("montant_annuel"))
            budget.ecart_ventilation = budget.budget_previsionnel - budget.total_lignes

    def _compute_appel_counts(self):
        Appel = self.env["coproerp.appel.charge"]
        for budget in self:
            budget.appel_budget_count = Appel.search_count(
                [("budget_origine_id", "=", budget.id), ("type_appel", "=", "budget_courant")]
            )
            budget.appel_fonds_count = Appel.search_count(
                [("budget_id", "=", budget.id), ("type_appel", "=", "fonds_travaux")]
            )

    # ------------------------------------------------------------------
    # Budget courant
    # ------------------------------------------------------------------
    def _verifier_budget_courant(self):
        self.ensure_one()
        if not self.active:
            raise UserError("Le budget doit être actif.")
        if not self.ligne_ids:
            raise UserError(
                "Ventilez d'abord le budget par clé de répartition "
                "(onglet « Répartition du budget »)."
            )
        if float_compare(self.total_lignes, self.budget_previsionnel, precision_digits=2):
            raise UserError(
                "Le total ventilé (%.2f €) ne correspond pas au budget voté (%.2f €)."
                % (self.total_lignes, self.budget_previsionnel)
            )
        mauvaises = self.ligne_ids.filtered(
            lambda l: l.repartition_id.type_repartition not in TYPES_CLE_BUDGET
        )
        if mauvaises:
            raise UserError(
                "Les clés de type fonds travaux ou travaux ne peuvent pas servir au "
                "budget courant : %s" % ", ".join(mauvaises.repartition_id.mapped("name"))
            )

    def _montant_ligne_periode(self, ligne, numero):
        """Montant à appeler pour ``ligne`` à l'échéance ``numero``.

        Reste à appeler sur l'année divisé par le nombre d'échéances restantes :
        la dernière échéance absorbe les arrondis, et une actualisation du
        budget en cours d'année est répartie sur les échéances suivantes.
        """
        Poste = self.env["coproerp.appel.charge.poste"]
        deja_appele = 0.0
        for numero_precedent in range(1, numero):
            poste = Poste.search(
                [
                    ("appel_id.budget_origine_id", "=", self.id),
                    ("appel_id.type_appel", "=", "budget_courant"),
                    ("appel_id.numero_appel_budget", "=", numero_precedent),
                    ("repartition_id", "=", ligne.repartition_id.id),
                ],
                limit=1,
            )
            deja_appele += poste.total_a_repartir if poste else ligne.montant_par_appel
        restantes = self.nombre_appels_budget - numero + 1
        return float_round(
            (ligne.montant_annuel - deja_appele) / restantes, precision_digits=2
        )

    def _generer_budget_courant(self, numeros):
        self.ensure_one()
        self._verifier_budget_courant()
        Appel = self.env["coproerp.appel.charge"]
        crees, messages = Appel.browse(), []
        for numero, debut, fin in Appel._periodes(self.date_debut, self.nombre_appels_budget):
            if numero not in numeros:
                continue
            lignes = [
                {
                    "type_poste": ligne.repartition_id.type_repartition,
                    "designation": ligne._libelle(),
                    "repartition": ligne.repartition_id,
                    "montant": self._montant_ligne_periode(ligne, numero),
                }
                for ligne in self.ligne_ids
            ]
            appels, msg = Appel._generer_appels(
                self.copropriete_id,
                lignes,
                {
                    "type_appel": "budget_courant",
                    "budget_origine_id": self.id,
                    "numero_appel_budget": numero,
                    "date_appel": debut - timedelta(days=self.delai_edition_jours),
                    "date_echeance": debut,
                    "date_debut_periode": debut,
                    "date_fin_periode": fin,
                    "note": "Budget %s — appel %s/%s."
                    % (self.reference, numero, self.nombre_appels_budget),
                },
                [
                    ("budget_origine_id", "=", self.id),
                    ("type_appel", "=", "budget_courant"),
                    ("numero_appel_budget", "=", numero),
                ],
                date_ref=debut,
            )
            crees |= appels
            messages += ["Échéance %s : %s" % (numero, m) for m in msg]
        return crees, messages

    def _prochain_numero(self, type_appel):
        Appel = self.env["coproerp.appel.charge"]
        nombre = self.nombre_appels_budget if type_appel == "budget_courant" else self.nombre_appels_fonds
        champ = "budget_origine_id" if type_appel == "budget_courant" else "budget_id"
        for numero in range(1, nombre + 1):
            if not Appel.search_count(
                [(champ, "=", self.id), ("type_appel", "=", type_appel),
                 ("numero_appel_budget", "=", numero)]
            ):
                return numero
        raise UserError("Toutes les échéances de ce budget ont déjà été générées.")

    def action_generer_appel_budget_suivant(self):
        self.ensure_one()
        numero = self._prochain_numero("budget_courant")
        appels, messages = self._generer_budget_courant({numero})
        return self.env["coproerp.appel.charge"]._action_resultat(
            appels, "Budget courant — échéance %s" % numero, messages
        )

    def action_generer_appels_budget_tous(self):
        self.ensure_one()
        appels, messages = self._generer_budget_courant(
            set(range(1, self.nombre_appels_budget + 1))
        )
        return self.env["coproerp.appel.charge"]._action_resultat(
            appels, "Budget courant — toutes les échéances", messages
        )

    # ------------------------------------------------------------------
    # Fonds travaux (remplace la génération d'origine)
    # ------------------------------------------------------------------
    def _cle_fonds_travaux(self):
        self.ensure_one()
        if self.repartition_fonds_travaux_id:
            return self.repartition_fonds_travaux_id
        cles = self.env["coproerp.repartition"].search([
            ("copropriete_id", "=", self.copropriete_id.id),
            ("type_repartition", "=", "fonds_travaux"),
            ("active", "=", True),
        ])
        if len(cles) != 1:
            raise UserError(
                "Choisissez la clé d'appel du fonds travaux sur le budget "
                "(par exemple : charges communes générales)."
            )
        return cles

    def _generer_fonds_travaux(self, numeros):
        self.ensure_one()
        if not self.active:
            raise UserError("Le budget doit être actif.")
        if self.cotisation_par_appel_fonds <= 0:
            raise UserError("La cotisation par appel du fonds travaux doit être positive.")
        cle = self._cle_fonds_travaux()
        Appel = self.env["coproerp.appel.charge"]
        crees, messages = Appel.browse(), []
        depart = self.date_premier_appel_fonds or self.date_debut
        for numero, debut, fin in Appel._periodes(depart, self.nombre_appels_fonds):
            if numero not in numeros:
                continue
            appels, msg = Appel._generer_appels(
                self.copropriete_id,
                [{
                    "type_poste": "fonds_travaux",
                    "designation": "FONDS OBLIGATOIRE TRAVAUX",
                    "repartition": cle,
                    "montant": self.cotisation_par_appel_fonds,
                }],
                {
                    "type_appel": "fonds_travaux",
                    "budget_id": self.id,
                    "numero_appel_budget": numero,
                    "date_appel": debut - timedelta(days=self.delai_edition_jours),
                    "date_echeance": debut,
                    "date_debut_periode": debut,
                    "date_fin_periode": fin,
                    "note": "Fonds travaux %s — appel %s/%s."
                    % (self.reference, numero, self.nombre_appels_fonds),
                },
                [
                    ("budget_id", "=", self.id),
                    ("type_appel", "=", "fonds_travaux"),
                    ("numero_appel_budget", "=", numero),
                ],
                date_ref=debut,
            )
            crees |= appels
            messages += ["Échéance %s : %s" % (numero, m) for m in msg]
        return crees, messages

    def action_generer_appels_fonds_travaux(self):
        """Toutes les échéances du fonds travaux (remplace la version d'origine)."""
        self.ensure_one()
        appels, messages = self._generer_fonds_travaux(
            set(range(1, self.nombre_appels_fonds + 1))
        )
        return self.env["coproerp.appel.charge"]._action_resultat(
            appels, "Fonds travaux — toutes les échéances", messages
        )

    def action_generer_appel_fonds_suivant(self):
        self.ensure_one()
        numero = self._prochain_numero("fonds_travaux")
        appels, messages = self._generer_fonds_travaux({numero})
        return self.env["coproerp.appel.charge"]._action_resultat(
            appels, "Fonds travaux — échéance %s" % numero, messages
        )

    def action_voir_appels_budget(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Appels du budget",
            "res_model": "coproerp.appel.charge",
            "view_mode": "list,form",
            "domain": ["|", ("budget_origine_id", "=", self.id), ("budget_id", "=", self.id)],
        }
