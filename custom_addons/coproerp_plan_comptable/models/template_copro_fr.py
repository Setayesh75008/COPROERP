import logging

from odoo import fields, models
from odoo.addons.account.models.chart_template import template

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    coproerp_dossier_copro = fields.Boolean(
        string="Dossier comptable de copropriété",
        readonly=True,
        copy=False,
        help="Société créée par CoproERP pour un syndicat : seul le plan "
        "comptable des copropriétés peut y être chargé.",
    )


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _load(self, template_code, company, install_demo, force_create=True):
        """Protège les dossiers de copropriété.

        À la création d'une société française, Odoo peut charger
        automatiquement le plan comptable général (« fr ») au moment de
        l'enregistrement en base, ce qui effacerait le plan des copropriétés.
        On l'ignore pour les dossiers de copropriété.
        """
        societe = company
        if isinstance(societe, int):
            societe = self.env["res.company"].browse(societe)
        if template_code != "copro_fr" and societe.sudo().coproerp_dossier_copro:
            _logger.info(
                "CoproERP : plan comptable %s non chargé pour %s (dossier de copropriété).",
                template_code, societe.name,
            )
            return None
        resultat = super()._load(template_code, company, install_demo, force_create=force_create)
        if template_code == "copro_fr":
            societe.sudo().coproerp_dossier_copro = True
        return resultat

    @template("copro_fr")
    def _get_copro_fr_template_data(self):
        return {
            "name": "Copropriété – plan comptable des syndicats (France)",
            # Pas de pays : le plan n'est jamais installé automatiquement sur
            # la société du cabinet ; il est chargé par CoproERP, dossier par dossier.
            "country": None,
            "code_digits": 6,
            "property_account_receivable_id": "copro_4501",
            "property_account_payable_id": "copro_401",
        }

    @template("copro_fr", "res.company")
    def _get_copro_fr_res_company(self):
        return {
            self.env.company.id: {
                "account_fiscal_country_id": "base.fr",
                "bank_account_code_prefix": "512",
                "cash_account_code_prefix": "53",
                "transfer_account_code_prefix": "58",
                "transfer_account_id": "copro_580",
                "account_journal_suspense_account_id": "copro_471",
                "income_account_id": "copro_714",
                "expense_account_id": "copro_615",
                "income_currency_exchange_account_id": "copro_771",
                "expense_currency_exchange_account_id": "copro_678",
                "default_cash_difference_income_account_id": "copro_771",
                "default_cash_difference_expense_account_id": "copro_678",
                "account_journal_early_pay_discount_gain_account_id": "copro_771",
                "account_journal_early_pay_discount_loss_account_id": "copro_678",
            },
        }

    @template("copro_fr", "account.journal")
    def _get_copro_fr_account_journal(self):
        return {
            "appels": {
                "name": "Appels de fonds",
                "type": "general",
                "code": "APF",
                "show_on_dashboard": True,
                "sequence": 1,
            },
            "purchase": {"name": "Achats (factures fournisseurs)", "code": "ACH"},
            "general": {"name": "Opérations diverses", "code": "OD"},
            "bank": {
                "name": "Banque (compte séparé)",
                "code": "BQ",
                "default_account_id": "copro_512",
            },
            "sale": {"name": "Ventes (non utilisé)", "code": "VTE", "show_on_dashboard": False},
        }
