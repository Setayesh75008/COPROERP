from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    coproerp_depense_id = fields.Many2one(
        "coproerp.depense", string="Facture fournisseur (CoproERP)", readonly=True, copy=False, index="btree_not_null"
    )
    coproerp_paiement_id = fields.Many2one(
        "coproerp.depense.paiement", string="Paiement fournisseur (CoproERP)", readonly=True, copy=False,
        index="btree_not_null",
    )


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    coproerp_repartition_id = fields.Many2one(
        "coproerp.repartition", string="Clé de répartition", index="btree_not_null", copy=True
    )
    coproerp_hors_budget = fields.Boolean(
        string="Hors budget (travaux)", copy=True,
        help="Dépense de travaux (art. 14-2) : non imputée sur le budget prévisionnel.",
    )
    coproerp_travaux_id = fields.Many2one(
        "coproerp.travaux", string="Opération de travaux", index="btree_not_null", copy=True
    )
