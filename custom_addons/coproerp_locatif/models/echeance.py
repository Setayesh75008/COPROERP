from odoo import api, fields, models
from odoo.exceptions import UserError

TYPES_LIGNE = [
    ("loyer", "Loyer"),
    ("charges", "Provision sur charges"),
    ("forfait", "Forfait de charges"),
    ("tva", "TVA"),
    ("depot", "Dépôt de garantie"),
    ("autre", "Autre"),
]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


class Echeance(models.Model):
    """Avis d'échéance d'un bail ; devient quittance une fois payé."""

    _name = "coproerp.locatif.echeance"
    _description = "Avis d'échéance / quittance"
    _order = "date_echeance desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    bail_id = fields.Many2one("coproerp.locatif.bail", string="Bail", required=True, index=True, ondelete="restrict")
    bien_id = fields.Many2one(related="bail_id.bien_id", store=True, string="Bien")
    locataire_id = fields.Many2one(related="bail_id.locataire_id", store=True, string="Locataire")
    proprietaire_id = fields.Many2one(related="bail_id.proprietaire_id", store=True, string="Propriétaire")
    type_echeance = fields.Selection([("loyer", "Loyer et charges"), ("depot", "Dépôt de garantie")],
                                     string="Objet", default="loyer", required=True)
    periode_debut = fields.Date(string="Du", required=True)
    periode_fin = fields.Date(string="Au", required=True)
    date_echeance = fields.Date(string="Exigible le", required=True)
    ligne_ids = fields.One2many("coproerp.locatif.echeance.ligne", "echeance_id", string="Détail")
    montant_total = fields.Float(string="Montant", compute="_compute_montants", store=True, digits=(16, 2))
    montant_loyer = fields.Float(string="Dont loyer", compute="_compute_montants", store=True, digits=(16, 2))
    montant_charges = fields.Float(string="Dont charges", compute="_compute_montants", store=True, digits=(16, 2))
    montant_paye = fields.Float(string="Payé", readonly=True, digits=(16, 2))
    montant_restant = fields.Float(string="Reste dû", readonly=True, digits=(16, 2))
    etat = fields.Selection([("emise", "Émis – à payer"), ("partielle", "Payé en partie"), ("payee", "Payé"),
                             ("annulee", "Annulé")], string="État", default="emise", readonly=True)
    annulee = fields.Boolean(string="Annulé", readonly=True, copy=False)
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)
    prorata = fields.Float(string="Prorata", digits=(6, 4), default=1.0, readonly=True)

    @api.depends("ligne_ids.montant", "ligne_ids.type_ligne")
    def _compute_montants(self):
        for echeance in self:
            lignes = echeance.ligne_ids
            echeance.montant_total = round(sum(lignes.mapped("montant")), 2)
            echeance.montant_loyer = round(sum(lignes.filtered(lambda l: l.type_ligne == "loyer").mapped("montant")), 2)
            echeance.montant_charges = round(sum(lignes.filtered(
                lambda l: l.type_ligne in ("charges", "forfait")).mapped("montant")), 2)

    def _maj_paiement(self):
        """Met à jour le montant payé et l'état d'après le lettrage du compte du locataire."""
        dossier = self.env["coproerp.locatif.dossier"].sudo().search([("company_id", "!=", False)], limit=1)
        compte = dossier.compte("locataires") if dossier else False
        for echeance in self:
            if echeance.annulee:
                echeance.write({"etat": "annulee", "montant_paye": 0.0, "montant_restant": 0.0})
                continue
            restant = echeance.montant_total
            if echeance.move_id and compte:
                lignes = echeance.move_id.sudo().line_ids.filtered(lambda l: l.account_id == compte)
                restant = round(sum(lignes.mapped("amount_residual")), 2)
            paye = round(echeance.montant_total - restant, 2)
            etat = "payee" if restant <= 0.004 else ("partielle" if paye > 0.004 else "emise")
            echeance.write({"etat": etat, "montant_paye": paye, "montant_restant": max(restant, 0.0)})

    # ------------------------------------------------------------------
    @api.model
    def _creer(self, bail, type_echeance, debut, fin, echeance, lignes, prorata=1.0):
        avis = self.create({
            "name": self.env["ir.sequence"].next_by_code("coproerp.locatif.echeance") or "/",
            "bail_id": bail.id, "type_echeance": type_echeance, "periode_debut": debut, "periode_fin": fin,
            "date_echeance": echeance, "prorata": prorata,
            "ligne_ids": [(0, 0, {"type_ligne": t, "libelle": libelle, "montant": round(m, 2)})
                          for t, libelle, m in lignes if round(m, 2)],
        })
        avis._comptabiliser()
        avis._maj_paiement()
        bail.lettrer()
        return avis

    @api.model
    def creer_loyer(self, bail, debut, fin, echeance):
        prorata = bail._prorata(debut, fin)
        mois = 3 if bail.periodicite == "trimestriel" else 1
        loyer = bail.loyer_hc * mois * prorata
        charges = bail.charges * mois * prorata
        lignes = [("loyer", "Loyer", loyer),
                  ("forfait" if bail.mode_charges == "forfait" else "charges",
                   "Forfait de charges" if bail.mode_charges == "forfait" else "Provision sur charges", charges)]
        if bail.tva:
            lignes.append(("tva", "TVA %s %%" % ("%g" % bail.taux_tva), (round(loyer, 2) + round(charges, 2))
                           * bail.taux_tva / 100))
        return self._creer(bail, "loyer", debut, fin, echeance, lignes, prorata)

    @api.model
    def creer_depot_garantie(self, bail):
        if bail.echeance_ids.filtered(lambda e: e.type_echeance == "depot" and not e.annulee):
            return self
        return self._creer(bail, "depot", bail.date_debut, bail.date_debut, bail.date_debut,
                           [("depot", "Dépôt de garantie", bail.depot_garantie)])

    def _comptabiliser(self):
        """Débit du compte du locataire ; crédit du compte du propriétaire (loyer, charges, TVA)
        ou du compte des dépôts de garantie, selon le mandat."""
        dossier = self.env["coproerp.locatif.dossier"].actif()
        for avis in self:
            bail = avis.bail_id
            libelle = "%s – %s – %s" % (avis.name, bail.locataire_id.name, avis.libelle_periode())
            lignes = [("locataires", bail.locataire_id, avis.montant_total, 0.0, libelle)]
            for ligne in avis.ligne_ids:
                if ligne.type_ligne == "depot":
                    cle, tiers = ("depots", bail.locataire_id) if bail.mandat_id.depot_conserve \
                        else ("proprietaires", bail.proprietaire_id)
                else:
                    cle, tiers = "proprietaires", bail.proprietaire_id
                lignes.append((cle, tiers, 0.0, ligne.montant, "%s – %s" % (ligne.libelle, libelle)))
            avis.move_id = dossier.ecriture("quittancement", avis.date_echeance, libelle, lignes)

    def action_annuler(self):
        for avis in self.filtered(lambda a: not a.annulee):
            if avis.montant_paye:
                raise UserError("L'avis %s a déjà reçu un paiement : annulez d'abord l'encaissement." % avis.name)
            if avis.move_id:
                avis.move_id.sudo()._reverse_moves(
                    [{"date": avis.move_id.date, "ref": "Annulation %s" % avis.name}], cancel=True)
            avis.annulee = True
            avis._maj_paiement()
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_locatif.action_report_avis_echeance").report_action(self)

    def action_imprimer_quittance(self):
        non_payees = self.filtered(lambda a: a.etat != "payee")
        if non_payees:
            raise UserError("Une quittance ne peut être délivrée que pour une échéance entièrement payée "
                            "(art. 21 de la loi de 1989) : %s." % ", ".join(non_payees.mapped("name")))
        return self.env.ref("coproerp_locatif.action_report_quittance").report_action(self)

    # ------------------------------------------------------------------
    def libelle_periode(self):
        self.ensure_one()
        if self.type_echeance == "depot":
            return "dépôt de garantie"
        d, f = self.periode_debut, self.periode_fin
        if d.day == 1 and d.month == f.month and d.year == f.year and f.day >= 28 and self.prorata == 1.0:
            return "%s %d" % (MOIS[d.month - 1], d.year)
        return "du %s au %s" % (d.strftime("%d/%m/%Y"), f.strftime("%d/%m/%Y"))

    def date_paiement(self):
        """Date du dernier paiement imputé sur l'avis."""
        self.ensure_one()
        if not self.move_id:
            return False
        lignes = self.move_id.sudo().line_ids.filtered(lambda l: l.debit > 0)
        dates = (lignes.matched_credit_ids.credit_move_id).mapped("date")
        return max(dates) if dates else False


class EcheanceLigne(models.Model):
    _name = "coproerp.locatif.echeance.ligne"
    _description = "Ligne d'avis d'échéance"
    _order = "id"

    echeance_id = fields.Many2one("coproerp.locatif.echeance", required=True, ondelete="cascade")
    type_ligne = fields.Selection(TYPES_LIGNE, string="Nature", required=True)
    libelle = fields.Char(string="Libellé", required=True)
    montant = fields.Float(string="Montant", digits=(16, 2))
