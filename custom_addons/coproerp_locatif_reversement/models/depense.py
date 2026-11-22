from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

CATEGORIES = [
    ("copropriete", "Charges de copropriété (appels de fonds du syndic)"),
    ("travaux", "Travaux de réparation et d'entretien"),
    ("amelioration", "Travaux d'amélioration"),
    ("assurance", "Assurance (propriétaire non occupant, loyers impayés)"),
    ("taxe_fonciere", "Taxe foncière"),
    ("teom", "Taxe d'enlèvement des ordures ménagères"),
    ("procedure", "Frais de procédure, d'huissier, d'avocat"),
    ("autre", "Autre"),
]


class DepenseProprietaire(models.Model):
    """Facture réglée sur les fonds d'un propriétaire, pour son compte."""

    _name = "coproerp.locatif.depense"
    _description = "Facture payée pour le compte d'un propriétaire"
    _inherit = ["mail.thread"]
    _order = "date_facture desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    mandat_id = fields.Many2one("coproerp.locatif.mandat", string="Mandat", required=True, index=True,
                                domain="[('etat', '=', 'actif')]")
    proprietaire_id = fields.Many2one(related="mandat_id.proprietaire_id", store=True, string="Propriétaire")
    bien_id = fields.Many2one("coproerp.locatif.bien", string="Bien concerné", domain="[('mandat_id', '=', mandat_id)]")
    fournisseur_id = fields.Many2one("res.partner", string="Fournisseur / créancier", required=True)
    categorie = fields.Selection(CATEGORIES, string="Nature", required=True, default="travaux")
    libelle = fields.Char(string="Objet", required=True)
    reference_facture = fields.Char(string="N° de facture")
    date_facture = fields.Date(string="Date de la facture", required=True, default=fields.Date.context_today)
    montant = fields.Float(string="Montant TTC", required=True, digits=(16, 2))
    date_paiement = fields.Date(string="Payée le", readonly=True, copy=False)
    piece = fields.Binary(string="Facture (pièce jointe)", attachment=True, copy=False)
    piece_nom = fields.Char(string="Nom du fichier")
    etat = fields.Selection([("brouillon", "À payer"), ("payee", "Payée"), ("annulee", "Annulée")], string="État",
                            default="brouillon", required=True, tracking=True)
    move_id = fields.Many2one("account.move", string="Écriture d'imputation", readonly=True, copy=False)
    move_paiement_id = fields.Many2one("account.move", string="Écriture de paiement", readonly=True, copy=False)

    @api.constrains("montant")
    def _check_montant(self):
        for depense in self:
            if depense.montant <= 0:
                raise ValidationError("Le montant de la facture doit être positif.")

    def action_payer(self, date_paiement=None):
        dossier = self.env["coproerp.locatif.dossier"].actif()
        Mandat = self.env["coproerp.locatif.mandat"]
        for depense in self.filtered(lambda d: d.etat == "brouillon"):
            proprietaire = depense.proprietaire_id
            situation = Mandat.situation_proprietaire(proprietaire)
            if depense.montant > situation["utilisable"] + 0.004:
                raise UserError(
                    "Les fonds de %s ne suffisent pas à payer cette facture de %s : %s disponibles "
                    "(solde %s, dont %s de loyers non encore encaissés).\n\nLe compte d'un mandant ne peut pas "
                    "devenir débiteur : les fonds des autres propriétaires ne peuvent pas servir à avancer cette "
                    "somme. Demandez au propriétaire d'alimenter son compte, ou attendez les prochains loyers."
                    % (proprietaire.name, _euros(depense.montant), _euros(situation["utilisable"]),
                       _euros(situation["solde"]), _euros(situation["impayes"])))
            if depense.name == "/":
                depense.name = self.env["ir.sequence"].next_by_code("coproerp.locatif.depense") or "/"
            jour = date_paiement or fields.Date.context_today(self)
            libelle = "%s – %s – %s%s" % (depense.name, depense.fournisseur_id.name, depense.libelle,
                                         " (fact. %s)" % depense.reference_facture if depense.reference_facture else "")
            ctx = dossier.with_context(locatif_nature="depense")
            depense.move_id = ctx.ecriture("achats", depense.date_facture, libelle, [
                ("proprietaires", proprietaire, depense.montant, 0.0, libelle),
                ("fournisseurs", depense.fournisseur_id, 0.0, depense.montant, libelle),
            ])
            banque = dossier.journal("banque").default_account_id
            depense.move_paiement_id = ctx.ecriture("banque", jour, "Paiement %s" % libelle, [
                ("fournisseurs", depense.fournisseur_id, depense.montant, 0.0, libelle),
                (banque, None, 0.0, depense.montant, libelle),
            ])
            compte = dossier.compte("fournisseurs")
            (depense.move_id | depense.move_paiement_id).line_ids.filtered(lambda l: l.account_id == compte).reconcile()
            depense.write({"etat": "payee", "date_paiement": jour})
        return True

    def action_annuler(self):
        for depense in self.filtered(lambda d: d.etat == "payee"):
            moves = (depense.move_id | depense.move_paiement_id).sudo()
            moves.line_ids.remove_move_reconcile()
            moves._reverse_moves([{"date": m.date, "ref": "Annulation %s" % depense.name} for m in moves], cancel=True)
            depense.etat = "annulee"
        return True

    def unlink(self):
        if any(d.etat != "brouillon" for d in self):
            raise UserError("Une facture payée ne se supprime pas : annulez son paiement.")
        return super().unlink()


def _euros(montant):
    return ("{:,.2f} €".format(montant or 0.0)).replace(",", " ").replace(".", ",")
