import logging

from odoo import fields, models
from odoo.addons.account.models.chart_template import template

_logger = logging.getLogger(__name__)

PLAN = "gerance_fr"


class ResCompany(models.Model):
    _inherit = "res.company"

    coproerp_dossier_gerance = fields.Boolean(
        string="Dossier des fonds des mandants (gestion locative)",
        readonly=True,
        copy=False,
        help="Société créée par CoproERP pour les fonds détenus pour le compte des propriétaires : "
             "seul le plan comptable de la gestion locative peut y être chargé.",
    )


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _load(self, template_code, company, install_demo, force_create=True):
        """Protège le dossier des mandants contre le chargement du plan comptable général."""
        societe = company
        if isinstance(societe, int):
            societe = self.env["res.company"].browse(societe)
        if template_code != PLAN and societe.sudo().coproerp_dossier_gerance:
            _logger.info("CoproERP : plan comptable %s non chargé pour %s (dossier des mandants).",
                         template_code, societe.name)
            return None
        resultat = super()._load(template_code, company, install_demo, force_create=force_create)
        if template_code == PLAN:
            societe.sudo().coproerp_dossier_gerance = True
        return resultat

    @template(PLAN)
    def _get_gerance_fr_template_data(self):
        return {
            "name": "Gestion locative – comptes des mandants (France)",
            "country": None,
            "code_digits": 6,
            "property_account_receivable_id": "ger_411",
            "property_account_payable_id": "ger_401",
        }

    @template(PLAN, "res.company")
    def _get_gerance_fr_res_company(self):
        return {
            self.env.company.id: {
                "account_fiscal_country_id": "base.fr",
                "bank_account_code_prefix": "512",
                "cash_account_code_prefix": "53",
                "transfer_account_code_prefix": "58",
                "transfer_account_id": "ger_580",
                "account_journal_suspense_account_id": "ger_471",
                "income_account_id": "ger_758",
                "expense_account_id": "ger_658",
                "income_currency_exchange_account_id": "ger_766",
                "expense_currency_exchange_account_id": "ger_666",
                "default_cash_difference_income_account_id": "ger_758",
                "default_cash_difference_expense_account_id": "ger_658",
                "account_journal_early_pay_discount_gain_account_id": "ger_758",
                "account_journal_early_pay_discount_loss_account_id": "ger_658",
            },
        }

    @template(PLAN, "account.journal")
    def _get_gerance_fr_account_journal(self):
        return {
            "quittancement": {
                "name": "Quittancement des loyers",
                "type": "general",
                "code": "QUI",
                "show_on_dashboard": True,
                "sequence": 1,
            },
            "purchase": {"name": "Factures pour le compte des propriétaires", "code": "ACH"},
            "general": {"name": "Opérations diverses", "code": "OD"},
            "bank": {
                "name": "Banque – compte des mandants",
                "code": "BQM",
                "default_account_id": "ger_512",
            },
            "sale": {"name": "Ventes (non utilisé)", "code": "VTE", "show_on_dashboard": False},
        }
