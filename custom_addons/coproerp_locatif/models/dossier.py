from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

PLAN = "gerance_fr"
JOURNAUX = {"quittancement": "QUI", "banque": "BQM", "od": "OD", "achats": "ACH"}
COMPTES = {
    "locataires": "411000",
    "proprietaires": "467100",
    "honoraires": "467200",
    "depots": "165000",
    "fournisseurs": "401000",
    "attente": "471000",
}


class DossierMandants(models.Model):
    """Dossier comptable des fonds détenus pour le compte des propriétaires mandants.

    Un seul dossier par cabinet : une société Odoo dédiée, avec son plan comptable,
    une banque des mandants et un sous-compte par propriétaire et par locataire.
    """

    _name = "coproerp.locatif.dossier"
    _description = "Dossier des fonds des mandants (gestion locative)"

    name = fields.Char(string="Libellé", required=True, default="Fonds des mandants – gestion locative")
    company_id = fields.Many2one("res.company", string="Dossier comptable", readonly=True, copy=False)
    banque_titulaire = fields.Char(string="Titulaire du compte des mandants")
    banque_nom = fields.Char(string="Banque")
    banque_iban = fields.Char(string="IBAN du compte des mandants")
    banque_bic = fields.Char(string="BIC")
    carte_professionnelle = fields.Char(string="Carte professionnelle / autorisation",
                                        help="Mention portée sur les mandats et les comptes rendus de gestion.")
    garant_financier = fields.Char(string="Garantie financière",
                                   help="Organisme et montant de la garantie des fonds détenus, le cas échéant.")
    jours_avant_relance = fields.Integer(string="Relance après (jours de retard)", default=10)
    jours_avant_mise_en_demeure = fields.Integer(string="Mise en demeure après la relance (jours)", default=15)
    delai_emission = fields.Integer(
        string="Émission des avis (jours avant l'échéance)", default=15,
        help="Le quittancement automatique émet chaque avis ce nombre de jours avant sa date d'échéance.")

    @api.constrains("name")
    def _check_unique(self):
        if self.search_count([]) > 1:
            raise ValidationError("Il n'y a qu'un dossier des mandants par cabinet.")

    @api.model
    def actif(self):
        dossier = self.sudo().search([], limit=1)
        if not dossier or not dossier.company_id:
            raise UserError("Le dossier des mandants n'est pas créé : Gestion locative → Configuration → "
                            "Dossier des mandants, bouton « Créer le dossier comptable ».")
        if dossier.company_id.chart_template != PLAN:
            raise UserError("Le dossier des mandants n'a pas le plan comptable de la gestion locative.")
        return dossier

    def action_creer_dossier_comptable(self):
        self.ensure_one()
        if self.company_id:
            raise UserError("Le dossier comptable des mandants existe déjà.")
        cabinet = self.env.company
        company = self.env["res.company"].sudo().create({
            "name": self.name,
            "currency_id": self.env.ref("base.EUR").id,
            "country_id": self.env.ref("base.fr").id,
            "street": cabinet.street or False,
            "zip": cabinet.zip or False,
            "city": cabinet.city or False,
            "coproerp_dossier_gerance": True,
        })
        utilisateurs = self.env["res.users"].sudo().search([
            ("share", "=", False), ("company_ids", "in", cabinet.ids)]) | self.env.user
        utilisateurs.write({"company_ids": [Command.link(company.id)]})
        self.env["account.chart.template"].sudo().try_loading(PLAN, company, install_demo=False)
        self.sudo().company_id = company
        company.sudo().restrictive_audit_trail = True
        journaux = self.env["account.journal"].sudo().search([
            ("company_id", "=", company.id), ("code", "in", list(JOURNAUX.values()))])
        journaux.write({"restrict_mode_hash_table": True})
        banque = journaux.filtered(lambda j: j.code == JOURNAUX["banque"])
        if banque and self.banque_iban:
            banque.bank_account_id = self.env["res.partner.bank"].sudo().create({
                "acc_number": self.banque_iban, "partner_id": company.partner_id.id})
        return True

    def action_voir_ecritures(self):
        dossier = self.actif()
        return {
            "type": "ir.actions.act_window", "name": "Écritures des mandants", "res_model": "account.move.line",
            "view_mode": "list,form", "domain": [("company_id", "=", dossier.company_id.id),
                                                 ("parent_state", "=", "posted")],
            "context": {"allowed_company_ids": [dossier.company_id.id] + self.env.companies.ids},
        }

    # ------------------------------------------------------------------
    def compte(self, cle):
        self.ensure_one()
        company = self.company_id.sudo()
        Account = self.env["account.account"].sudo().with_company(company)
        compte = Account.search([*Account._check_company_domain(company), ("code", "=", COMPTES[cle])], limit=1)
        if not compte:
            raise UserError("Le compte %s n'existe pas dans le dossier des mandants." % COMPTES[cle])
        return compte

    def journal(self, cle):
        self.ensure_one()
        company = self.company_id.sudo()
        journal = self.env["account.journal"].sudo().search(
            [("company_id", "=", company.id), ("code", "=", JOURNAUX[cle])], limit=1)
        if not journal:
            raise UserError("Journal %s introuvable dans le dossier des mandants." % JOURNAUX[cle])
        return journal

    def ecriture(self, journal, date, libelle, lignes):
        """Crée et valide une écriture du dossier des mandants.

        lignes : liste de (clé de compte ou compte, partenaire, débit, crédit, libellé).
        """
        self.ensure_one()
        company = self.company_id.sudo()
        # Un montant négatif passe dans l'autre colonne (avoir, trop-perçu à rendre…).
        lignes = [(cle, partner, max(debit, 0.0) + max(-credit, 0.0), max(credit, 0.0) + max(-debit, 0.0), nom)
                  for cle, partner, debit, credit, nom in lignes]
        move = self.env["account.move"].sudo().with_company(company).create({
            "move_type": "entry", "journal_id": self.journal(journal).id, "date": date, "ref": libelle,
            "line_ids": [Command.create({
                "account_id": (cle if isinstance(cle, models.BaseModel) else self.compte(cle)).id, "partner_id": partner.id if partner else False,
                "debit": round(debit, 2), "credit": round(credit, 2), "name": nom or libelle,
            }) for cle, partner, debit, credit, nom in lignes if round(debit, 2) or round(credit, 2)],
        })
        move.action_post()
        return move
