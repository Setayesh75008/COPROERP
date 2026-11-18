from collections import OrderedDict
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class RegularisationCharges(models.Model):
    """Régularisation annuelle des charges récupérables d'un bail (art. 23 de la loi du 6 juillet 1989)."""

    _name = "coproerp.locatif.regularisation"
    _description = "Régularisation des charges locatives"
    _inherit = ["mail.thread"]
    _order = "date_fin desc, id desc"

    name = fields.Char(string="Régularisation", compute="_compute_name", store=True)
    bail_id = fields.Many2one("coproerp.locatif.bail", string="Bail", required=True, index=True, ondelete="cascade",
                              domain="[('etat', 'in', ('en_cours', 'termine'))]")
    locataire_id = fields.Many2one(related="bail_id.locataire_id", store=True, string="Locataire")
    proprietaire_id = fields.Many2one(related="bail_id.proprietaire_id", store=True, string="Propriétaire")
    bien_id = fields.Many2one(related="bail_id.bien_id", store=True, string="Bien")
    date_debut = fields.Date(string="Du", required=True, default=lambda self: date(fields.Date.context_today(self).year - 1, 1, 1))
    date_fin = fields.Date(string="Au", required=True, default=lambda self: date(fields.Date.context_today(self).year - 1, 12, 31))
    provisions = fields.Float(string="Provisions appelées", digits=(16, 2), readonly=True)
    ligne_ids = fields.One2many("coproerp.locatif.regularisation.ligne", "regularisation_id",
                                string="Charges réelles récupérables")
    total_reel = fields.Float(string="Charges réelles", compute="_compute_totaux", store=True, digits=(16, 2))
    solde = fields.Float(string="Solde", compute="_compute_totaux", store=True, digits=(16, 2),
                         help="Positif : complément dû par le locataire. Négatif : trop-perçu à lui rembourser.")
    nouvelle_provision = fields.Float(string="Nouvelle provision mensuelle proposée", compute="_compute_totaux",
                                      store=True, digits=(16, 2))
    appliquer_provision = fields.Boolean(string="Ajuster la provision mensuelle du bail", default=True)
    avis_id = fields.Many2one("coproerp.locatif.echeance", string="Avis de régularisation", readonly=True)
    etat = fields.Selection([("brouillon", "En préparation"), ("validee", "Validée"), ("annulee", "Annulée")],
                            string="État", default="brouillon", required=True, tracking=True)
    note = fields.Text(string="Mode de répartition / observations",
                       help="Précisez, si besoin, comment les charges de l'immeuble ont été réparties entre les "
                            "locataires (tantièmes, surface…) : cette mention figure sur le décompte.")

    @api.depends("bail_id", "date_debut", "date_fin")
    def _compute_name(self):
        for reg in self:
            reg.name = "Charges %s – %s" % (reg.bail_id.name or "", reg.date_fin.year if reg.date_fin else "")

    @api.depends("ligne_ids.montant", "provisions", "date_debut", "date_fin")
    def _compute_totaux(self):
        for reg in self:
            reg.total_reel = round(sum(reg.ligne_ids.mapped("montant")), 2)
            reg.solde = round(reg.total_reel - reg.provisions, 2)
            mois = 12.0
            if reg.date_debut and reg.date_fin:
                jours = (reg.date_fin - reg.date_debut).days + 1
                mois = max(jours / 365.0 * 12.0, 1.0)
            reg.nouvelle_provision = round(reg.total_reel / mois, 2) if reg.total_reel else 0.0

    @api.constrains("date_debut", "date_fin", "bail_id")
    def _check_periode(self):
        for reg in self:
            if reg.date_fin < reg.date_debut:
                raise ValidationError("La fin de la période précède son début.")
            if reg.bail_id.mode_charges == "forfait":
                raise ValidationError("Les charges du bail %s sont forfaitaires : elles ne se régularisent pas."
                                      % reg.bail_id.name)
            chevauchement = self.search([("bail_id", "=", reg.bail_id.id), ("etat", "=", "validee"),
                                         ("id", "!=", reg.id), ("date_debut", "<=", reg.date_fin),
                                         ("date_fin", ">=", reg.date_debut)], limit=1)
            if chevauchement:
                raise ValidationError("Cette période chevauche une régularisation déjà validée (%s)."
                                      % chevauchement.name)

    @api.onchange("bail_id")
    def _onchange_bail(self):
        if self.bail_id:
            self._ajuster_periode()

    def _ajuster_periode(self):
        """Limite la période à l'occupation du locataire."""
        for reg in self:
            bail = reg.bail_id
            if bail.date_debut and reg.date_debut < bail.date_debut:
                reg.date_debut = bail.date_debut
            if bail.date_sortie and reg.date_fin > bail.date_sortie:
                reg.date_fin = bail.date_sortie

    @api.model_create_multi
    def create(self, vals_list):
        regs = super().create(vals_list)
        regs._ajuster_periode()
        return regs

    # ------------------------------------------------------------------
    def action_calculer_provisions(self):
        for reg in self.filtered(lambda r: r.etat == "brouillon"):
            avis = reg.bail_id.echeance_ids.filtered(
                lambda e: e.type_echeance == "loyer" and not e.annulee
                and e.periode_debut >= reg.date_debut and e.periode_fin <= reg.date_fin)
            lignes = avis.ligne_ids.filtered(lambda l: l.type_ligne == "charges")
            reg.provisions = round(sum(lignes.mapped("montant")), 2)
        return True

    def action_reprendre_copropriete(self):
        """Reprend la part récupérable des factures de la copropriété, au prorata des tantièmes du lot."""
        for reg in self.filtered(lambda r: r.etat == "brouillon"):
            lot = reg.bien_id.lot_id
            if not lot:
                raise UserError("Le bien %s n'est pas rattaché à un lot de copropriété : saisissez les charges "
                                "réelles à la main." % reg.bien_id.name)
            par_nature = OrderedDict()
            lignes = self.env["coproerp.depense.ligne"].sudo().search([
                ("copropriete_id", "=", lot.copropriete_id.id), ("depense_id.etat", "=", "validee"),
                ("depense_id.date_facture", ">=", reg.date_debut), ("depense_id.date_facture", "<=", reg.date_fin),
            ])
            for ligne in lignes:
                quote = ligne.repartition_id.line_ids.filtered(lambda l: l.lot_id == lot)
                total = ligne.repartition_id.total_tantiemes
                if not quote or not total:
                    continue
                part = ligne.nature_id.part_recuperable(ligne.montant)
                if not part:
                    continue
                signe = -1.0 if getattr(ligne.depense_id, "type_piece", "facture") == "avoir" else 1.0
                montant = signe * part * sum(quote.mapped("tantiemes")) / total
                par_nature[ligne.nature_id] = par_nature.get(ligne.nature_id, 0.0) + montant
            reg.ligne_ids.filtered(lambda l: l.origine == "copropriete").unlink()
            reg.write({"ligne_ids": [(0, 0, {
                "nature_id": nature.id, "libelle": nature.display_name, "montant": round(montant, 2),
                "origine": "copropriete"}) for nature, montant in par_nature.items() if round(montant, 2)]})
        return True

    def action_valider(self):
        for reg in self.filtered(lambda r: r.etat == "brouillon"):
            reg.action_calculer_provisions()
            if not reg.ligne_ids:
                raise UserError("Saisissez les charges réelles récupérables de la période.")
            if reg.solde:
                libelle = "Régularisation des charges du %s au %s" % (
                    reg.date_debut.strftime("%d/%m/%Y"), reg.date_fin.strftime("%d/%m/%Y"))
                reg.avis_id = self.env["coproerp.locatif.echeance"]._creer(
                    reg.bail_id, "regularisation", reg.date_debut, reg.date_fin, fields.Date.context_today(self),
                    [("charges", libelle, reg.solde)])
            if reg.appliquer_provision and reg.bail_id.etat == "en_cours":
                reg.bail_id.charges = reg.nouvelle_provision
            reg.etat = "validee"
        return True

    def action_annuler(self):
        for reg in self.filtered(lambda r: r.etat == "validee"):
            if reg.avis_id:
                reg.avis_id.action_annuler()
            reg.etat = "annulee"
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_locatif_charges.action_report_regularisation").report_action(self)


class RegularisationLigne(models.Model):
    _name = "coproerp.locatif.regularisation.ligne"
    _description = "Charge réelle récupérable"
    _order = "id"

    regularisation_id = fields.Many2one("coproerp.locatif.regularisation", required=True, ondelete="cascade")
    nature_id = fields.Many2one("coproerp.nature.depense", string="Nature")
    libelle = fields.Char(string="Libellé", required=True)
    montant = fields.Float(string="Montant récupérable", digits=(16, 2))
    origine = fields.Selection([("manuel", "Saisie"), ("copropriete", "Copropriété")], string="Origine",
                               default="manuel", readonly=True)

    @api.onchange("nature_id")
    def _onchange_nature(self):
        if self.nature_id and not self.libelle:
            self.libelle = self.nature_id.display_name
