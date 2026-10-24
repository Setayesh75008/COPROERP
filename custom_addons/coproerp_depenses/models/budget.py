from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class BudgetLigne(models.Model):
    _inherit = "coproerp.budget.ligne"

    montant_realise = fields.Float(
        string="Réalisé", compute="_compute_realise", digits=(16, 2),
        help="Dépenses comptabilisées sur l'exercice pour cette clé "
        "(hors travaux décidés par l'assemblée).",
    )
    ecart_realise = fields.Float(
        string="Écart (budget − réalisé)", compute="_compute_realise", digits=(16, 2)
    )

    def _compute_realise(self):
        MoveLine = self.env["account.move.line"].sudo()
        for ligne in self:
            budget = ligne.budget_id
            company = budget.copropriete_id.company_id
            realise = 0.0
            if company and ligne.repartition_id and budget.date_debut and budget.date_fin:
                lignes = MoveLine.search([
                    ("company_id", "=", company.id),
                    ("parent_state", "=", "posted"),
                    ("account_id.account_type", "in", ("expense", "expense_other")),
                    ("coproerp_repartition_id", "=", ligne.repartition_id.id),
                    ("coproerp_hors_budget", "=", False),
                    ("date", ">=", budget.date_debut),
                    ("date", "<=", budget.date_fin),
                ])
                realise = round(sum(lignes.mapped("balance")), 2)
            ligne.montant_realise = realise
            ligne.ecart_realise = round(ligne.montant_annuel - realise, 2)


class BudgetAnnuel(models.Model):
    _inherit = "coproerp.budget.annuel"

    depense_ids = fields.One2many("coproerp.depense", "budget_id", string="Factures de l'exercice")
    total_realise = fields.Float(string="Total réalisé", compute="_compute_total_realise", digits=(16, 2))

    def _compute_total_realise(self):
        for budget in self:
            budget.total_realise = round(sum(budget.ligne_ids.mapped("montant_realise")), 2)

    def action_voir_depenses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Factures – %s" % (self.display_name or ""),
            "res_model": "coproerp.depense",
            "view_mode": "list,form",
            "domain": [("budget_id", "=", self.id)],
            "context": {"default_copropriete_id": self.copropriete_id.id},
        }


class BudgetDetail(models.Model):
    """Budget prévisionnel détaillé par nature de charge, à l'intérieur de chaque clé.

    Le total des natures d'une clé alimente automatiquement la ligne du budget
    par clé, qui sert au calcul des appels de fonds.
    """

    _name = "coproerp.budget.detail"
    _description = "Budget prévisionnel par nature de charge"
    _order = "budget_id, repartition_id, nature_code, id"

    budget_id = fields.Many2one("coproerp.budget.annuel", required=True, ondelete="cascade", index=True)
    copropriete_id = fields.Many2one(related="budget_id.copropriete_id", store=True)
    repartition_id = fields.Many2one(
        "coproerp.repartition", string="Clé de répartition", required=True, ondelete="restrict",
        domain="[('copropriete_id', '=', copropriete_id)]",
    )
    nature_id = fields.Many2one(
        "coproerp.nature.depense", string="Nature de charge", required=True, ondelete="restrict",
        domain="[('travaux', '=', False)]",
    )
    nature_code = fields.Char(related="nature_id.code", store=True, string="Compte")
    montant = fields.Float(string="Budget", digits=(16, 2), required=True)
    montant_realise = fields.Float(string="Réalisé", compute="_compute_realise", digits=(16, 2))
    ecart = fields.Float(string="Écart (budget − réalisé)", compute="_compute_realise", digits=(16, 2))

    _detail_unique = models.Constraint(
        "UNIQUE(budget_id, repartition_id, nature_id)",
        "Cette nature figure déjà dans le budget pour cette clé.",
    )

    @api.constrains("montant")
    def _check_montant(self):
        for detail in self:
            if detail.montant < 0:
                raise ValidationError("Le montant budgété ne peut pas être négatif.")

    @api.constrains("repartition_id", "budget_id")
    def _check_cle(self):
        for detail in self:
            if detail.repartition_id.copropriete_id != detail.budget_id.copropriete_id:
                raise ValidationError("La clé de répartition doit appartenir à la copropriété du budget.")

    def _compute_realise(self):
        MoveLine = self.env["account.move.line"].sudo()
        for detail in self:
            budget = detail.budget_id
            company = budget.copropriete_id.company_id
            realise = 0.0
            if company and detail.nature_id and budget.date_debut and budget.date_fin:
                try:
                    compte = budget.copropriete_id.sudo()._compte(detail.nature_id.code)
                except UserError:
                    compte = False
                if compte:
                    lignes = MoveLine.search([
                        ("company_id", "=", company.id),
                        ("parent_state", "=", "posted"),
                        ("account_id", "=", compte.id),
                        ("coproerp_repartition_id", "=", detail.repartition_id.id),
                        ("coproerp_hors_budget", "=", False),
                        ("date", ">=", budget.date_debut),
                        ("date", "<=", budget.date_fin),
                    ])
                    realise = round(sum(lignes.mapped("balance")), 2)
            detail.montant_realise = realise
            detail.ecart = round(detail.montant - realise, 2)

    # -- synchronisation avec le budget par clé --------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        details = super().create(vals_list)
        details.budget_id._synchroniser_budget_par_cle()
        return details

    def write(self, vals):
        budgets = self.budget_id
        resultat = super().write(vals)
        (budgets | self.budget_id)._synchroniser_budget_par_cle()
        return resultat

    def unlink(self):
        budgets = self.budget_id
        cles = {(d.budget_id, d.repartition_id) for d in self}
        resultat = super().unlink()
        budgets._synchroniser_budget_par_cle(cles_supprimees=cles)
        return resultat


class BudgetAnnuelDetail(models.Model):
    _inherit = "coproerp.budget.annuel"

    detail_ids = fields.One2many("coproerp.budget.detail", "budget_id", string="Budget par nature de charge")

    def _synchroniser_budget_par_cle(self, cles_supprimees=None):
        """Reporte le total des natures de chaque clé sur la ligne du budget par clé."""
        Ligne = self.env["coproerp.budget.ligne"]
        for budget in self.exists():
            totaux = {}
            for detail in budget.detail_ids:
                totaux[detail.repartition_id] = totaux.get(detail.repartition_id, 0.0) + detail.montant
            # Clé dont toutes les natures ont été supprimées : la ligne passe à zéro
            for (b, cle) in (cles_supprimees or set()):
                if b == budget and cle not in totaux:
                    totaux[cle] = 0.0
            for cle, total in totaux.items():
                total = round(total, 2)
                ligne = budget.ligne_ids.filtered(lambda l: l.repartition_id == cle)[:1]
                if ligne:
                    if round(ligne.montant_annuel, 2) != total:
                        ligne.montant_annuel = total
                elif total:
                    Ligne.create({
                        "budget_id": budget.id, "repartition_id": cle.id,
                        "designation": (cle.name or "").upper(), "montant_annuel": total,
                    })

    def action_preremplir_detail(self):
        """Propose le budget par nature à partir des dépenses réalisées de l'exercice précédent."""
        for budget in self:
            if budget.detail_ids:
                raise UserError("Le budget par nature est déjà renseigné : videz-le avant de le pré-remplir.")
            precedent = self.search([
                ("copropriete_id", "=", budget.copropriete_id.id),
                ("date_fin", "<", budget.date_debut),
            ], order="date_fin desc", limit=1)
            if not precedent:
                raise UserError("Aucun exercice précédent pour cette copropriété.")
            company = budget.copropriete_id._verifier_dossier()
            lignes = self.env["account.move.line"].sudo().search([
                ("company_id", "=", company.id),
                ("parent_state", "=", "posted"),
                ("account_id.account_type", "in", ("expense", "expense_other")),
                ("coproerp_hors_budget", "=", False),
                ("coproerp_repartition_id", "!=", False),
                ("date", ">=", precedent.date_debut),
                ("date", "<=", precedent.date_fin),
            ])
            natures = {n.code: n for n in self.env["coproerp.nature.depense"].search([("travaux", "=", False)])}
            montants = {}
            for ligne in lignes:
                nature = natures.get(ligne.account_id.with_company(company).code)
                if nature:
                    cle = (ligne.coproerp_repartition_id, nature)
                    montants[cle] = montants.get(cle, 0.0) + ligne.balance
            if not montants:
                raise UserError("Aucune dépense comptabilisée sur l'exercice précédent.")
            self.env["coproerp.budget.detail"].create([{
                "budget_id": budget.id, "repartition_id": cle.id, "nature_id": nature.id,
                "montant": round(max(montant, 0.0), 2),
            } for (cle, nature), montant in montants.items()])
        return True

    def budget_par_nature(self):
        """{(clé, code compte): montant} et {code compte: montant} du budget détaillé."""
        self.ensure_one()
        par_cle, par_code = {}, {}
        for detail in self.detail_ids:
            code = detail.nature_id.code
            par_cle[(detail.repartition_id, code)] = par_cle.get((detail.repartition_id, code), 0.0) + detail.montant
            par_code[code] = par_code.get(code, 0.0) + detail.montant
        return par_cle, par_code
