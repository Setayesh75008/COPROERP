import base64
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

COMPTE_FRAIS = "714000"  # Produits divers (dont frais de recouvrement art. 10-1)
DELAI_19_2 = 30  # jours (art. 19-2 de la loi du 10 juillet 1965)

MODES_ENVOI = [
    ("courrier", "Courrier simple"),
    ("email", "Courrier électronique"),
    ("lrar", "Lettre recommandée avec accusé de réception"),
    ("lre", "Lettre recommandée électronique"),
]


class Relance(models.Model):
    """Lettre de relance ou mise en demeure adressée à un copropriétaire débiteur."""

    _name = "coproerp.relance"
    _description = "Relance ou mise en demeure"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    type_relance = fields.Selection(
        [("relance", "Lettre de relance"), ("mise_en_demeure", "Mise en demeure")],
        string="Type", required=True, default="relance", tracking=True,
    )
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="restrict",
    )
    personne_id = fields.Many2one(
        "res.partner", string="Copropriétaire", required=True, index=True, ondelete="restrict",
    )
    date = fields.Date(string="Date de la lettre", required=True, default=fields.Date.context_today)
    date_debut_releve = fields.Date(
        string="Relevé de compte à partir du",
        help="Par défaut : date de l'échéance impayée la plus ancienne.",
    )
    montant_du = fields.Float(string="Montant réclamé", digits=(16, 2), readonly=True, copy=False)
    frais = fields.Float(
        string="Frais de mise en demeure", digits=(16, 2),
        help="Imputés au seul copropriétaire défaillant (art. 10-1 de la loi du 10 juillet 1965).",
    )
    delai_jours = fields.Integer(string="Délai de paiement (jours)")
    mode_envoi = fields.Selection(MODES_ENVOI, string="Mode d'envoi", required=True, default="courrier")
    adresse_email = fields.Char(string="Adresse électronique d'envoi")
    numero_envoi = fields.Char(string="N° de recommandé / preuve de dépôt", tracking=True)
    date_presentation = fields.Date(
        string="Date de première présentation",
        help="Lettre recommandée : date de première présentation (ou de réception de la lettre "
             "recommandée électronique). Le délai court à compter de cette date.",
        tracking=True,
    )
    date_limite = fields.Date(string="Fin du délai", compute="_compute_date_limite", store=True)
    etat = fields.Selection(
        [("brouillon", "Brouillon"), ("envoyee", "Envoyée"), ("annulee", "Annulée")],
        string="État", default="brouillon", required=True, readonly=True, copy=False, tracking=True,
    )
    date_envoi = fields.Date(string="Envoyée le", readonly=True, copy=False)
    move_frais_id = fields.Many2one("account.move", string="Écriture des frais", readonly=True, copy=False)
    move_frais_annulation_id = fields.Many2one(
        "account.move", string="Annulation des frais", readonly=True, copy=False)
    relance_precedente_id = fields.Many2one(
        "coproerp.relance", string="Relance précédente", compute="_compute_relance_precedente")
    solde_actuel = fields.Float(string="Solde actuel", digits=(16, 2), compute="_compute_solde_actuel")
    regle = fields.Boolean(string="Compte soldé", compute="_compute_solde_actuel")
    exigibilite_anticipee = fields.Boolean(
        string="Art. 19-2 applicable", compute="_compute_solde_actuel",
        help="Mise en demeure restée infructueuse plus de trente jours : les provisions non encore "
             "échues de l'exercice deviennent exigibles et le président du tribunal judiciaire peut "
             "être saisi selon la procédure accélérée au fond.",
    )
    note = fields.Text(string="Observations")

    # ------------------------------------------------------------------
    @api.depends("date", "date_presentation", "delai_jours", "type_relance")
    def _compute_date_limite(self):
        for relance in self:
            if relance.type_relance != "mise_en_demeure" or not relance.date:
                relance.date_limite = False
            else:
                depart = relance.date_presentation or relance.date
                relance.date_limite = depart + timedelta(days=relance.delai_jours or DELAI_19_2)

    def _compute_relance_precedente(self):
        for relance in self:
            relance.relance_precedente_id = self.search([
                ("copropriete_id", "=", relance.copropriete_id.id),
                ("personne_id", "=", relance.personne_id.id),
                ("etat", "=", "envoyee"),
                ("type_relance", "=", "relance"),
                ("date", "<=", relance.date),
                ("id", "!=", relance._origin.id or 0),
            ], order="date desc, id desc", limit=1) if relance.personne_id and relance.date else False

    def _compute_solde_actuel(self):
        aujourdhui = fields.Date.context_today(self)
        for relance in self:
            solde = 0.0
            if relance.copropriete_id.company_id and relance.personne_id:
                solde = relance.copropriete_id.situation_debiteur(relance.personne_id, aujourdhui)["solde"]
            relance.solde_actuel = solde
            relance.regle = solde <= 0.005
            relance.exigibilite_anticipee = bool(
                relance.type_relance == "mise_en_demeure" and relance.etat == "envoyee"
                and relance.date_limite and aujourdhui > relance.date_limite and not relance.regle
            )

    @api.constrains("date")
    def _check_date(self):
        for relance in self:
            if relance.date and relance.date > fields.Date.context_today(relance):
                raise ValidationError("La date d'une relance ne peut pas être dans le futur.")

    # ------------------------------------------------------------------
    @api.model
    def _mode_par_defaut(self, personne, type_relance, date):
        mode, adresse = self.env["coproerp.notification.mode"].mode_au(personne, date)
        if type_relance == "mise_en_demeure":
            return ("lre", adresse) if mode == "electronique" else ("lrar", False)
        return ("email", adresse) if mode == "electronique" else ("courrier", False)

    @api.model_create_multi
    def create(self, vals_list):
        Copro = self.env["coproerp.copropriete"]
        Partner = self.env["res.partner"]
        for vals in vals_list:
            copro = Copro.browse(vals.get("copropriete_id"))
            personne = Partner.browse(vals.get("personne_id"))
            type_relance = vals.get("type_relance") or "relance"
            date = fields.Date.to_date(vals.get("date")) or fields.Date.context_today(self)
            if "mode_envoi" not in vals and personne:
                mode, adresse = self._mode_par_defaut(personne, type_relance, date)
                vals["mode_envoi"] = mode
                vals.setdefault("adresse_email", adresse or False)
            if type_relance == "mise_en_demeure":
                vals.setdefault("frais", copro.recouvrement_frais_mise_en_demeure)
                vals.setdefault("delai_jours", copro.recouvrement_delai_mise_en_demeure or DELAI_19_2)
            if not vals.get("date_debut_releve") and copro.company_id and personne:
                situation = copro.situation_debiteur(personne, date)
                vals["date_debut_releve"] = situation["plus_ancienne"] or date.replace(month=1, day=1)
        return super().create(vals_list)

    def write(self, vals):
        verrouilles = {"type_relance", "copropriete_id", "personne_id", "date", "frais", "date_debut_releve"}
        if verrouilles & set(vals) and self.filtered(lambda r: r.etat != "brouillon"):
            raise UserError("Une relance envoyée ne peut plus être modifiée : annulez-la et refaites-la.")
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda r: r.etat != "brouillon"):
            raise UserError("Seule une relance en brouillon peut être supprimée.")
        return super().unlink()

    # ------------------------------------------------------------------
    def _comptabiliser_frais(self):
        """Imputation des frais au copropriétaire : débit 450, crédit 714 (clé des
        honoraires de recouvrement), pour qu'ils viennent en déduction des charges
        des autres copropriétaires lors de la régularisation."""
        self.ensure_one()
        copro = self.copropriete_id
        company = copro._verifier_dossier()
        if not copro.recouvrement_cle_frais_id:
            raise UserError(
                "Indiquez la « clé des honoraires de recouvrement » dans l'onglet Recouvrement "
                "de la copropriété avant d'imputer des frais de mise en demeure.")
        libelle = "Frais de mise en demeure %s (art. 10-1)" % self.name
        move = self.env["account.move"].with_company(company).create({
            "move_type": "entry",
            "journal_id": copro._journal("od").id,
            "date": self.date,
            "ref": "%s %s" % (self.name, self.personne_id.name or ""),
            "line_ids": [
                Command.create({
                    "account_id": copro._compte(copro.compte_copro_budget).id,
                    "partner_id": self.personne_id.id,
                    "name": "Frais de mise en demeure",
                    "debit": round(self.frais, 2),
                }),
                Command.create({
                    "account_id": copro._compte(COMPTE_FRAIS).id,
                    "partner_id": self.personne_id.id,
                    "name": libelle,
                    "credit": round(self.frais, 2),
                    "coproerp_repartition_id": copro.recouvrement_cle_frais_id.id,
                }),
            ],
        })
        move.action_post()
        return move

    def action_envoyer(self):
        for relance in self.filtered(lambda r: r.etat == "brouillon"):
            copro = relance.copropriete_id
            copro._verifier_dossier()
            situation = copro.situation_debiteur(relance.personne_id, relance.date)
            if situation["solde"] <= 0.005:
                raise UserError("Le compte de %s n'est pas débiteur au %s : rien à réclamer."
                                % (relance.personne_id.name, relance.date.strftime("%d/%m/%Y")))
            if relance.mode_envoi in ("email", "lre") and not (relance.adresse_email or "").strip():
                raise UserError("Indiquez l'adresse électronique d'envoi.")
            if relance.name == "/":
                code = "coproerp.relance.%s" % (
                    "mise_en_demeure" if relance.type_relance == "mise_en_demeure" else "simple")
                relance.name = self.env["ir.sequence"].next_by_code(code) or "/"
            vals = {"etat": "envoyee", "date_envoi": fields.Date.context_today(relance)}
            if relance.type_relance == "mise_en_demeure" and relance.frais > 0:
                vals["move_frais_id"] = relance._comptabiliser_frais().id
            # Montant figé au moment de l'envoi (frais compris)
            vals["montant_du"] = copro.situation_debiteur(relance.personne_id, relance.date)["solde"]
            super(Relance, relance).write(vals)
            if relance.mode_envoi == "email":
                relance._envoyer_par_email()
            relance.message_post(body="%s envoyée (%s)." % (
                dict(self._fields["type_relance"].selection)[relance.type_relance],
                dict(MODES_ENVOI)[relance.mode_envoi]))
        return True

    def _envoyer_par_email(self):
        """Relance simple par courrier électronique, PDF joint."""
        self.ensure_one()
        rapport = self.env.ref("coproerp_recouvrement.action_report_relance")
        pdf, _format = self.env["ir.actions.report"].with_context(discard_logo_check=True)._render_qweb_pdf(
            rapport.report_name, self.ids)
        piece = self.env["ir.attachment"].create({
            "name": "%s.pdf" % self.name.replace("/", "-"),
            "datas": base64.b64encode(pdf),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/pdf",
        })
        copro = self.copropriete_id.sudo()
        corps = (
            "<p>Madame, Monsieur,</p>"
            "<p>Vous trouverez ci-joint un rappel concernant votre compte de copropriétaire "
            "de la résidence %s.</p>"
            "<p>Si vous avez effectué ce paiement très récemment, merci de ne pas tenir compte "
            "de ce rappel.</p><p>Cordialement,<br/>Le syndic</p>" % (copro.name or "")
        )
        self.env["mail.mail"].sudo().create({
            "subject": "Rappel – %s – %s" % (copro.name or "", self.name),
            "email_to": self.adresse_email.strip(),
            "body_html": corps,
            "attachment_ids": [Command.link(piece.id)],
            "model": self._name,
            "res_id": self.id,
        })

    def action_annuler(self):
        for relance in self.filtered(lambda r: r.etat == "envoyee"):
            vals = {"etat": "annulee"}
            if relance.move_frais_id and relance.move_frais_id.state == "posted":
                company = relance.copropriete_id._verifier_dossier()
                move = relance.move_frais_id.with_company(company)
                date = max(fields.Date.context_today(relance), move.date)
                annulation = move._reverse_moves(
                    [{"date": date, "ref": "Annulation %s" % (move.ref or "")}], cancel=True)
                vals["move_frais_annulation_id"] = annulation.id
            super(Relance, relance).write(vals)
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_recouvrement.action_report_relance").report_action(self)

    # ------------------------------------------------------------------
    def donnees_lettre(self):
        self.ensure_one()
        copro = self.copropriete_id.sudo()
        date_debut = self.date_debut_releve or self.date.replace(month=1, day=1)
        releve = copro.donnees_releve(self.personne_id, min(date_debut, self.date), self.date)
        montant = self.montant_du if self.etat == "envoyee" else releve["solde_final"]
        recommande = self.mode_envoi in ("lrar", "lre")
        return {
            "relance": self,
            "copro": copro,
            "personne": self.personne_id,
            "releve": releve,
            "montant": round(montant, 2),
            "mise_en_demeure": self.type_relance == "mise_en_demeure",
            "precedente": self.relance_precedente_id,
            "mode_libelle": dict(MODES_ENVOI)[self.mode_envoi],
            "recommande": recommande,
            "delai": self.delai_jours or DELAI_19_2,
            "projet": self.etat == "brouillon",
        }
