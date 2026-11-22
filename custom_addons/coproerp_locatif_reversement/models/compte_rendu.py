from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

RUBRIQUES = [
    ("quittancement", "Loyers, charges et régularisations appelés"),
    ("honoraires", "Honoraires de gestion"),
    ("depense", "Factures payées pour votre compte"),
    ("reversement", "Virements reçus"),
    ("autre", "Autres opérations"),
]


class CompteRenduGestion(models.Model):
    """Compte rendu de gestion d'un mandat pour une période ; sa validation prélève les honoraires."""

    _name = "coproerp.locatif.compte_rendu"
    _description = "Compte rendu de gestion"
    _inherit = ["mail.thread"]
    _order = "date_fin desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    mandat_id = fields.Many2one("coproerp.locatif.mandat", string="Mandat", required=True, index=True,
                                domain="[('etat', '!=', 'brouillon')]")
    proprietaire_id = fields.Many2one(related="mandat_id.proprietaire_id", store=True, string="Propriétaire")
    date_debut = fields.Date(string="Du", required=True)
    date_fin = fields.Date(string="Au", required=True)
    base_honoraires = fields.Float(string="Sommes encaissées soumises aux honoraires", digits=(16, 2), readonly=True,
                                   help="Paiements reçus des locataires sur la période, dépôts de garantie exclus.")
    taux_honoraires = fields.Float(string="Taux (% TTC)", digits=(5, 2), readonly=True)
    honoraires = fields.Float(string="Honoraires TTC", digits=(16, 2), readonly=True)
    move_honoraires_id = fields.Many2one("account.move", string="Écriture des honoraires", readonly=True, copy=False)
    solde_debut = fields.Float(string="Solde au début de la période", digits=(16, 2), readonly=True)
    total_quittancement = fields.Float(string="Loyers et charges appelés", digits=(16, 2), readonly=True)
    total_honoraires = fields.Float(string="Honoraires", digits=(16, 2), readonly=True)
    total_depenses = fields.Float(string="Factures payées", digits=(16, 2), readonly=True)
    total_reversements = fields.Float(string="Virements effectués", digits=(16, 2), readonly=True)
    total_autres = fields.Float(string="Autres opérations", digits=(16, 2), readonly=True)
    solde_fin = fields.Float(string="Solde en fin de période", digits=(16, 2), readonly=True)
    impayes = fields.Float(string="Loyers non encore encaissés", digits=(16, 2), readonly=True)
    reserve = fields.Float(string="Réserve conservée", digits=(16, 2), readonly=True)
    disponible = fields.Float(string="Disponible à virer", digits=(16, 2), readonly=True)
    reversement_ids = fields.One2many("coproerp.locatif.reversement", "compte_rendu_id", string="Virements")
    etat = fields.Selection([("brouillon", "En préparation"), ("valide", "Validé"), ("annule", "Annulé")],
                            string="État", default="brouillon", required=True, tracking=True)
    note = fields.Text(string="Observations du gestionnaire",
                       help="Figure sur le compte rendu : travaux en cours, locataire en retard, congé reçu…")

    @api.model
    def debut_suivant(self, mandat):
        dernier = self.search([("mandat_id", "=", mandat.id), ("etat", "=", "valide")], order="date_fin desc", limit=1)
        return dernier.date_fin + timedelta(days=1) if dernier else mandat.date_effet

    @api.onchange("mandat_id")
    def _onchange_mandat(self):
        if self.mandat_id and not self.date_debut:
            self.date_debut = self.debut_suivant(self.mandat_id)

    @api.constrains("date_debut", "date_fin", "mandat_id", "etat")
    def _check_periode(self):
        for crg in self:
            if crg.date_fin < crg.date_debut:
                raise ValidationError("La fin de la période précède son début.")
            if crg.etat != "valide":
                continue
            autre = self.search([("mandat_id", "=", crg.mandat_id.id), ("etat", "=", "valide"), ("id", "!=", crg.id),
                                 ("date_debut", "<=", crg.date_fin), ("date_fin", ">=", crg.date_debut)], limit=1)
            if autre:
                raise ValidationError("La période chevauche le compte rendu %s, déjà validé : les honoraires "
                                      "seraient prélevés deux fois." % autre.name)

    # ------------------------------------------------------------------
    def _encaissements(self):
        self.ensure_one()
        return self.env["coproerp.locatif.encaissement"].sudo().search([
            ("bail_id.mandat_id", "=", self.mandat_id.id), ("etat", "=", "valide"),
            ("date", ">=", self.date_debut), ("date", "<=", self.date_fin)])

    @api.model
    def part_depot(self, encaissement):
        """Part d'un encaissement imputée sur un dépôt de garantie."""
        dossier = self.env["coproerp.locatif.mandat"].dossier_mandants()
        compte = dossier.compte("locataires")
        Echeance = self.env["coproerp.locatif.echeance"].sudo()
        part = 0.0
        for ligne in encaissement.move_id.sudo().line_ids.filtered(lambda l: l.account_id == compte):
            for partiel in ligne.matched_debit_ids:
                avis = Echeance.search([("move_id", "=", partiel.debit_move_id.move_id.id)], limit=1)
                if avis.type_echeance == "depot":
                    part += partiel.amount
        return round(part, 2)

    def action_calculer(self):
        for crg in self.filtered(lambda c: c.etat == "brouillon"):
            base = sum(enc.montant - self.part_depot(enc) for enc in crg._encaissements())
            taux = crg.mandat_id.taux_honoraires
            crg.write({"base_honoraires": round(base, 2), "taux_honoraires": taux,
                       "honoraires": round(base * taux / 100.0, 2)})
            crg._photographier()
        return True

    def _photographier(self):
        """Fige les totaux du relevé du compte du propriétaire sur la période."""
        Mandat = self.env["coproerp.locatif.mandat"]
        for crg in self:
            proprietaire = crg.proprietaire_id
            totaux = {cle: 0.0 for cle, _libelle in RUBRIQUES}
            for ligne in crg.lignes_releve():
                totaux[crg.rubrique(ligne)] += -ligne.balance
            situation = Mandat.situation_proprietaire(proprietaire)
            crg.write({
                "solde_debut": Mandat.solde_compte(proprietaire, au=crg.date_debut - timedelta(days=1)),
                "total_quittancement": round(totaux["quittancement"], 2),
                "total_honoraires": round(totaux["honoraires"], 2),
                "total_depenses": round(totaux["depense"], 2),
                "total_reversements": round(totaux["reversement"], 2),
                "total_autres": round(totaux["autre"], 2),
                "solde_fin": Mandat.solde_compte(proprietaire, au=crg.date_fin),
                "impayes": situation["impayes"], "reserve": situation["reserve"],
                "disponible": situation["disponible"],
            })

    def action_valider(self):
        for crg in self.filtered(lambda c: c.etat == "brouillon"):
            crg.action_calculer()
            if crg.name == "/":
                crg.name = self.env["ir.sequence"].next_by_code("coproerp.locatif.compte_rendu") or "/"
            crg.etat = "valide"  # contrôle du chevauchement avant de passer l'écriture
            if crg.honoraires:
                dossier = self.env["coproerp.locatif.dossier"].actif().with_context(locatif_nature="honoraires")
                libelle = "%s – Honoraires de gestion %g %% du %s au %s" % (
                    crg.name, crg.taux_honoraires, crg.date_debut.strftime("%d/%m/%Y"),
                    crg.date_fin.strftime("%d/%m/%Y"))
                crg.move_honoraires_id = dossier.ecriture("od", crg.date_fin, libelle, [
                    ("proprietaires", crg.proprietaire_id, crg.honoraires, 0.0, libelle),
                    ("honoraires", None, 0.0, crg.honoraires, libelle),
                ])
            crg._photographier()
        return True

    def action_annuler(self):
        for crg in self.filtered(lambda c: c.etat == "valide"):
            if crg.reversement_ids.filtered(lambda r: r.etat == "valide"):
                raise UserError("Un virement lié à ce compte rendu a été validé : annulez-le d'abord.")
            crg.reversement_ids.filtered(lambda r: r.etat == "brouillon").unlink()
            if crg.move_honoraires_id:
                crg.move_honoraires_id.sudo()._reverse_moves(
                    [{"date": crg.move_honoraires_id.date, "ref": "Annulation %s" % crg.name}], cancel=True)
            crg.etat = "annule"
        return True

    def action_preparer_virement(self):
        """Prépare le virement du disponible au propriétaire."""
        Reversement = self.env["coproerp.locatif.reversement"]
        for crg in self.filtered(lambda c: c.etat == "valide"):
            if crg.reversement_ids.filtered(lambda r: r.etat != "annule"):
                continue
            disponible = self.env["coproerp.locatif.mandat"].situation_proprietaire(crg.proprietaire_id)["disponible"]
            if disponible > 0:
                Reversement.create({"mandat_id": crg.mandat_id.id, "compte_rendu_id": crg.id,
                                    "montant": disponible, "date": fields.Date.context_today(self)})
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_locatif_reversement.action_report_compte_rendu").report_action(self)

    def unlink(self):
        if any(c.etat == "valide" for c in self):
            raise UserError("Un compte rendu validé ne se supprime pas : annulez-le.")
        return super().unlink()

    # ------------------------------------------------------------------
    # Données du compte rendu imprimé
    # ------------------------------------------------------------------
    def lignes_releve(self):
        self.ensure_one()
        dossier = self.env["coproerp.locatif.mandat"].dossier_mandants()
        if not dossier:
            return self.env["account.move.line"]
        return self.env["account.move.line"].sudo().search([
            ("company_id", "=", dossier.company_id.id), ("account_id", "=", dossier.compte("proprietaires").id),
            ("partner_id", "=", self.proprietaire_id.id), ("parent_state", "=", "posted"),
            ("date", ">=", self.date_debut), ("date", "<=", self.date_fin)], order="date, id")

    @api.model
    def rubrique(self, ligne):
        move = ligne.move_id
        if move.locatif_nature in ("honoraires", "depense", "reversement"):
            return move.locatif_nature
        if move.journal_id.code == "QUI":
            return "quittancement"
        return "autre"

    def situation_baux(self):
        """Pour chaque bail du mandat : appelé et encaissé sur la période, reste dû à ce jour."""
        self.ensure_one()
        resultat = []
        baux = self.env["coproerp.locatif.bail"].sudo().search([("mandat_id", "=", self.mandat_id.id),
                                                                ("etat", "!=", "brouillon")])
        for bail in baux:
            avis = bail.echeance_ids.filtered(
                lambda a: not a.annulee and a.type_echeance != "depot"
                and self.date_debut <= a.date_echeance <= self.date_fin)
            encaisse = bail.encaissement_ids.filtered(
                lambda e: e.etat == "valide" and self.date_debut <= e.date <= self.date_fin)
            reste = sum(bail.echeance_ids.filtered(
                lambda a: not a.annulee and a.type_echeance != "depot").mapped("montant_restant"))
            if not (avis or encaisse or reste) and bail.etat != "en_cours":
                continue
            resultat.append({"bail": bail, "appele": round(sum(avis.mapped("montant_total")), 2),
                             "encaisse": round(sum(e.montant - self.part_depot(e) for e in encaisse), 2), "reste": round(reste, 2)})
        return resultat
