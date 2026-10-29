from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

COMPTE_INDEMNITES = "713000"  # Indemnités d'assurances

NATURES_SINISTRE = [
    ("degat_eaux", "Dégât des eaux"),
    ("incendie", "Incendie, explosion"),
    ("vol", "Vol, tentative de vol"),
    ("vandalisme", "Vandalisme"),
    ("bris_glace", "Bris de glace"),
    ("tempete", "Tempête, grêle, neige"),
    ("catnat", "Catastrophe naturelle"),
    ("responsabilite", "Responsabilité civile (dommage causé à un tiers)"),
    ("autre", "Autre"),
]


def ajouter_jours_ouvres(date, jours):
    """Ajoute des jours ouvrés (du lundi au vendredi, jours fériés non pris en compte)."""
    while jours > 0:
        date += timedelta(days=1)
        if date.weekday() < 5:
            jours -= 1
    return date


class Sinistre(models.Model):
    """Sinistre touchant l'immeuble : déclaration à l'assureur, expertise, indemnisation."""

    _name = "coproerp.sinistre"
    _description = "Sinistre"
    _inherit = ["mail.thread"]
    _order = "date_sinistre desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, tracking=True)
    nature = fields.Selection(NATURES_SINISTRE, string="Nature", required=True, tracking=True)
    date_sinistre = fields.Date(string="Date du sinistre", required=True, tracking=True)
    date_connaissance = fields.Date(
        string="Connu du syndic le", help="Le délai de déclaration court à partir de la connaissance du sinistre.")
    date_arrete_catnat = fields.Date(string="Publication de l'arrêté de catastrophe naturelle")
    description = fields.Text(string="Circonstances et dommages constatés", required=True)
    localisation = fields.Selection(
        [("communes", "Parties communes"), ("privatives", "Parties privatives"), ("mixte", "Parties communes et privatives")],
        string="Localisation", default="communes", required=True)
    lot_ids = fields.Many2many("coproerp.lot", "coproerp_sinistre_lot_rel", "sinistre_id", "lot_id",
                               string="Lots concernés", domain="[('copropriete_id', '=', copropriete_id)]")
    tiers_id = fields.Many2one("res.partner", string="Tiers responsable ou lésé")
    contrat_id = fields.Many2one(
        "coproerp.contrat", string="Contrat d'assurance", tracking=True,
        domain="[('copropriete_id', '=', copropriete_id), ('type_contrat', 'in', ('assurance', 'dommages_ouvrage'))]")
    assureur_id = fields.Many2one(related="contrat_id.prestataire_id", string="Assureur")
    date_limite_declaration = fields.Date(
        string="Déclaration au plus tard le", compute="_compute_date_limite", store=True,
        help="Code des assurances : 5 jours ouvrés (art. L. 113-2), 2 jours ouvrés en cas de vol, 30 jours après la "
             "publication de l'arrêté en cas de catastrophe naturelle (art. L. 125-1), sauf délai plus long au contrat.")
    date_declaration = fields.Date(string="Déclaré le", tracking=True)
    numero_dossier = fields.Char(string="N° de dossier chez l'assureur", tracking=True)
    expert_id = fields.Many2one("res.partner", string="Expert")
    date_expertise = fields.Date(string="Date de l'expertise")
    montant_dommages = fields.Float(string="Montant des dommages (devis)", digits=(16, 2))
    franchise = fields.Float(string="Franchise", digits=(16, 2))
    indemnite_attendue = fields.Float(string="Indemnité attendue", compute="_compute_indemnite", digits=(16, 2))
    indemnite_recue = fields.Float(string="Indemnité reçue", digits=(16, 2), readonly=True, tracking=True)
    date_encaissement = fields.Date(string="Encaissée le", readonly=True)
    repartition_id = fields.Many2one(
        "coproerp.repartition", string="Clé de répartition des réparations",
        domain="[('copropriete_id', '=', copropriete_id)]",
        help="L'indemnité vient en déduction des charges de cette clé (celle des factures de réparation).")
    move_indemnite_id = fields.Many2one("account.move", string="Écriture d'encaissement", readonly=True, copy=False)
    etat = fields.Selection(
        [("a_declarer", "À déclarer"), ("declare", "Déclaré"), ("expertise", "Expertise"),
         ("indemnise", "Indemnisé"), ("clos", "Clos"), ("refuse", "Refusé / sans suite")],
        string="État", default="a_declarer", required=True, tracking=True)
    retard = fields.Boolean(string="Déclaration en retard", compute="_compute_retard")
    note = fields.Text(string="Suivi")

    @api.depends("nature", "date_sinistre", "date_connaissance", "date_arrete_catnat")
    def _compute_date_limite(self):
        for sinistre in self:
            depart = sinistre.date_connaissance or sinistre.date_sinistre
            if sinistre.nature == "catnat":
                sinistre.date_limite_declaration = (
                    sinistre.date_arrete_catnat + timedelta(days=30) if sinistre.date_arrete_catnat else False)
            elif depart:
                sinistre.date_limite_declaration = ajouter_jours_ouvres(depart, 2 if sinistre.nature == "vol" else 5)
            else:
                sinistre.date_limite_declaration = False

    @api.depends("date_limite_declaration", "date_declaration")
    def _compute_retard(self):
        aujourdhui = fields.Date.context_today(self)
        for sinistre in self:
            limite = sinistre.date_limite_declaration
            reference = sinistre.date_declaration or aujourdhui
            sinistre.retard = bool(limite and reference > limite)

    @api.depends("montant_dommages", "franchise")
    def _compute_indemnite(self):
        for sinistre in self:
            sinistre.indemnite_attendue = max(sinistre.montant_dommages - sinistre.franchise, 0.0)

    @api.constrains("date_sinistre", "date_declaration")
    def _check_dates(self):
        aujourdhui = fields.Date.context_today(self)
        for sinistre in self:
            if sinistre.date_sinistre and sinistre.date_sinistre > aujourdhui:
                raise ValidationError("La date du sinistre ne peut pas être dans le futur.")
            if sinistre.date_declaration and sinistre.date_declaration < sinistre.date_sinistre:
                raise ValidationError("La déclaration ne peut pas précéder le sinistre.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.sinistre") or "/"
        return super().create(vals_list)

    def action_declarer(self):
        for sinistre in self:
            if not sinistre.contrat_id:
                raise UserError("Indiquez le contrat d'assurance concerné.")
            sinistre.write({"etat": "declare", "date_declaration": sinistre.date_declaration
                            or fields.Date.context_today(sinistre)})
        return self.env.ref("coproerp_gestion_courante.action_report_declaration_sinistre").report_action(self)

    def action_imprimer_declaration(self):
        return self.env.ref("coproerp_gestion_courante.action_report_declaration_sinistre").report_action(self)

    def action_encaisser_indemnite(self, montant=None, date=None):
        """Encaissement de l'indemnité : débit banque / crédit 713 (indemnités d'assurance), sur la clé
        des réparations, pour qu'elle vienne en déduction des charges correspondantes."""
        for sinistre in self:
            montant = montant if montant is not None else sinistre.indemnite_attendue
            date = date or fields.Date.context_today(sinistre)
            if montant <= 0:
                raise UserError("Indiquez le montant des dommages et la franchise : l'indemnité est nulle.")
            if sinistre.move_indemnite_id:
                raise UserError("L'indemnité est déjà encaissée.")
            if not sinistre.repartition_id:
                raise UserError("Indiquez la clé de répartition des réparations.")
            copro = sinistre.copropriete_id
            company = copro._verifier_dossier()
            journal = copro._journal("banque")
            libelle = "Indemnité d'assurance sinistre %s %s" % (sinistre.name, sinistre.numero_dossier or "")
            move = self.env["account.move"].with_company(company).create({
                "move_type": "entry", "journal_id": journal.id, "date": date, "ref": libelle,
                "line_ids": [
                    Command.create({"account_id": journal.default_account_id.id, "name": libelle,
                                    "partner_id": sinistre.assureur_id.id or False, "debit": round(montant, 2)}),
                    Command.create({"account_id": copro._compte(COMPTE_INDEMNITES).id, "name": libelle,
                                    "partner_id": sinistre.assureur_id.id or False, "credit": round(montant, 2),
                                    "coproerp_repartition_id": sinistre.repartition_id.id}),
                ],
            })
            move.action_post()
            sinistre.write({"indemnite_recue": montant, "date_encaissement": date,
                            "move_indemnite_id": move.id, "etat": "indemnise"})
        return True

    def libelle_nature(self):
        self.ensure_one()
        return dict(NATURES_SINISTRE).get(self.nature, "")
