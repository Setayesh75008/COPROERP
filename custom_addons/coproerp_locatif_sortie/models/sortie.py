from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.coproerp_locatif.models.bail import HABITATION
from odoo.addons.coproerp_locatif_reversement.models.depense import _euros

NATURES_RETENUE = [
    ("reparations", "Réparations locatives, remise en état (hors vétusté)"),
    ("nettoyage", "Nettoyage"),
    ("cles", "Clés ou badges non restitués"),
    ("charges", "Charges (arrêté provisoire)"),
    ("autre", "Autre"),
]


class SortieLocataire(models.Model):
    """Sortie du locataire : congé, décompte et restitution du dépôt de garantie (art. 22 de la loi de 1989)."""

    _name = "coproerp.locatif.sortie"
    _description = "Sortie du locataire et restitution du dépôt de garantie"
    _inherit = ["mail.thread"]
    _order = "date_remise_cles desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    bail_id = fields.Many2one("coproerp.locatif.bail", string="Bail", required=True, index=True,
                              domain="[('etat', 'in', ('en_cours', 'termine'))]")
    locataire_id = fields.Many2one(related="bail_id.locataire_id", store=True, string="Locataire")
    proprietaire_id = fields.Many2one(related="bail_id.proprietaire_id", store=True, string="Propriétaire")
    bien_id = fields.Many2one(related="bail_id.bien_id", store=True, string="Bien")
    depot_conserve = fields.Boolean(related="bail_id.mandat_id.depot_conserve", string="Dépôt détenu par le cabinet")
    date_conge = fields.Date(string="Congé reçu le")
    date_fin_preavis = fields.Date(string="Fin du préavis", compute="_compute_fin_preavis")
    date_remise_cles = fields.Date(string="Clés remises le", required=True)
    nouvelle_adresse = fields.Text(string="Nouvelle adresse du locataire",
                                   help="Sans elle, la majoration pour restitution tardive n'est pas due.")
    etat_lieux_id = fields.Many2one("coproerp.locatif.etat_lieux", string="État des lieux de sortie",
                                    compute="_compute_etat_lieux", store=True, readonly=False,
                                    domain="[('bail_id', '=', bail_id), ('type_edl', '=', 'sortie')]")
    conforme = fields.Boolean(string="Sortie conforme à l'entrée", compute="_compute_conformite", store=True)
    regime_legal = fields.Boolean(string="Logement (loi de 1989)", compute="_compute_conformite", store=True)
    delai_mois = fields.Integer(string="Délai de restitution (mois)", compute="_compute_delai_mois", store=True,
                                readonly=False)
    date_limite = fields.Date(string="À restituer au plus tard le", compute="_compute_date_limite", store=True)
    en_retard = fields.Boolean(string="Délai dépassé", compute="_compute_en_retard")
    depot_verse = fields.Float(string="Dépôt de garantie versé", compute="_compute_depot", digits=(16, 2))
    retenue_ids = fields.One2many("coproerp.locatif.sortie.retenue", "sortie_id", string="Retenues")
    total_retenues = fields.Float(string="Total des retenues", compute="_compute_retenues", store=True,
                                  digits=(16, 2))
    immeuble_copropriete = fields.Boolean(string="Logement en copropriété", compute="_compute_copropriete",
                                          store=True, readonly=False)
    reserve = fields.Float(string="Provision pour charges conservée", digits=(16, 2),
                           help="Au plus 20 % du dépôt, jusqu'à l'approbation des comptes de la copropriété ; "
                                "le solde est alors restitué dans le mois.")
    # Arrêté du décompte
    impayes = fields.Float(string="Loyers et charges restant dus", digits=(16, 2), readonly=True)
    solde_final = fields.Float(string="Solde du décompte", digits=(16, 2), readonly=True,
                               help="Positif : à restituer au locataire. Négatif : reste dû par le locataire.")
    avis_retenues_id = fields.Many2one("coproerp.locatif.echeance", string="Avis des retenues", readonly=True)
    move_ids = fields.Many2many("account.move", "coproerp_locatif_sortie_move_rel", "sortie_id", "move_id",
                                string="Écritures", readonly=True, copy=False)
    # Restitution
    date_restitution = fields.Date(string="Restitué le", readonly=True)
    mois_retard = fields.Integer(string="Mois de retard", readonly=True)
    majoration = fields.Float(string="Majoration pour retard", digits=(16, 2), readonly=True)
    montant_restitue = fields.Float(string="Montant restitué", digits=(16, 2), readonly=True)
    # Solde de la provision
    date_approbation = fields.Date(string="Comptes de la copropriété approuvés le")
    charges_definitives = fields.Float(string="Charges dues après approbation des comptes", digits=(16, 2),
                                       help="Complément de charges dû par le locataire pour sa période "
                                            "d'occupation (négatif s'il a trop payé).")
    reserve_soldee = fields.Boolean(string="Provision soldée", readonly=True)
    montant_restitue_reserve = fields.Float(string="Solde de la provision restitué", digits=(16, 2), readonly=True)
    etat = fields.Selection([("brouillon", "En préparation"), ("arrete", "Décompte arrêté"),
                             ("restitue", "Restitué"), ("annule", "Annulé")], string="État", default="brouillon",
                            required=True, tracking=True)

    # ------------------------------------------------------------------
    @api.depends("date_conge", "bail_id.preavis_mois")
    def _compute_fin_preavis(self):
        for sortie in self:
            sortie.date_fin_preavis = (sortie.date_conge + relativedelta(months=sortie.bail_id.preavis_mois)
                                       if sortie.date_conge else False)

    @api.depends("bail_id")
    def _compute_etat_lieux(self):
        for sortie in self:
            if sortie.bail_id and not sortie.etat_lieux_id:
                sortie.etat_lieux_id = self.env["coproerp.locatif.etat_lieux"].search([
                    ("bail_id", "=", sortie.bail_id.id), ("type_edl", "=", "sortie")], order="date desc", limit=1)
            else:
                sortie.etat_lieux_id = sortie.etat_lieux_id

    @api.depends("bail_id.bien_id.lot_id")
    def _compute_copropriete(self):
        for sortie in self:
            sortie.immeuble_copropriete = bool(sortie.bail_id.bien_id.lot_id)

    # Un calcul par champ : une valeur saisie pour l'un n'empêche pas le calcul des autres.
    @api.depends("bail_id.type_bail", "etat_lieux_id.conforme", "etat_lieux_id.etat")
    def _compute_conformite(self):
        for sortie in self:
            edl = sortie.etat_lieux_id
            sortie.conforme = bool(edl and edl.etat == "signe" and edl.conforme)
            sortie.regime_legal = sortie.bail_id.type_bail in HABITATION

    @api.depends("conforme", "regime_legal")
    def _compute_delai_mois(self):
        for sortie in self:
            # Un mois si l'état des lieux de sortie est conforme à celui d'entrée, deux mois sinon (art. 22) ;
            # hors logement, le délai prévu au bail (deux mois par défaut).
            if sortie.regime_legal or not sortie.delai_mois:
                sortie.delai_mois = 1 if sortie.regime_legal and sortie.conforme else 2
            else:
                sortie.delai_mois = sortie.delai_mois

    @api.depends("date_remise_cles", "delai_mois")
    def _compute_date_limite(self):
        for sortie in self:
            sortie.date_limite = (sortie.date_remise_cles + relativedelta(months=sortie.delai_mois)
                                  if sortie.date_remise_cles else False)

    def _compute_en_retard(self):
        aujourdhui = fields.Date.context_today(self)
        for sortie in self:
            sortie.en_retard = bool(sortie.etat == "arrete" and sortie.date_limite and sortie.date_limite < aujourdhui)

    def _compute_depot(self):
        for sortie in self:
            avis = sortie.bail_id.echeance_ids.filtered(lambda e: e.type_echeance == "depot" and not e.annulee)
            sortie.depot_verse = round(sum(avis.mapped("montant_paye")), 2)

    @api.depends("retenue_ids.montant")
    def _compute_retenues(self):
        for sortie in self:
            sortie.total_retenues = round(sum(sortie.retenue_ids.mapped("montant")), 2)

    @api.constrains("reserve", "immeuble_copropriete")
    def _check_reserve(self):
        for sortie in self:
            if sortie.reserve < 0:
                raise ValidationError("La provision conservée ne peut pas être négative.")
            if sortie.reserve and not sortie.immeuble_copropriete:
                raise ValidationError("Une provision pour charges ne peut être conservée que pour un logement "
                                      "situé dans un immeuble en copropriété.")
            if sortie.regime_legal and sortie.reserve > round(sortie.bail_id.depot_garantie * 0.2, 2) + 0.004:
                raise ValidationError("La provision conservée ne peut pas dépasser 20 %% du dépôt de garantie, "
                                      "soit %s (art. 22 de la loi de 1989)." % _euros(sortie.bail_id.depot_garantie * 0.2))

    @api.constrains("bail_id", "etat")
    def _check_unique(self):
        for sortie in self.filtered(lambda s: s.etat != "annule"):
            if self.search_count([("bail_id", "=", sortie.bail_id.id), ("etat", "!=", "annule"),
                                  ("id", "!=", sortie.id)]):
                raise ValidationError("Un décompte de sortie existe déjà pour le bail %s." % sortie.bail_id.name)

    @api.onchange("date_conge", "bail_id")
    def _onchange_conge(self):
        if self.date_fin_preavis and not self.date_remise_cles:
            self.date_remise_cles = self.date_fin_preavis

    # ------------------------------------------------------------------
    # Écritures
    # ------------------------------------------------------------------
    def _ecriture(self, journal, date, libelle, lignes):
        dossier = self.env["coproerp.locatif.dossier"].actif().with_context(locatif_nature="sortie")
        move = dossier.ecriture(journal, date, libelle, lignes)
        self.move_ids = [(4, move.id)]
        return move

    def _transferer_depot(self, montant, date, libelle):
        """Affecte le dépôt de garantie au compte du locataire, où il paie ce qui reste dû."""
        self.ensure_one()
        if round(montant, 2) <= 0:
            return
        bail = self.bail_id
        if self.depot_conserve:
            source = ("depots", bail.locataire_id)
        else:  # le dépôt a été reversé au propriétaire : c'est lui qui le rend
            source = ("proprietaires", bail.proprietaire_id)
        self._ecriture("od", date, libelle, [
            (source[0], source[1], montant, 0.0, libelle),
            ("locataires", bail.locataire_id, 0.0, montant, libelle),
        ])

    def _rembourser(self, date, libelle):
        """Vire au locataire le crédit de son compte ; rend le montant viré."""
        self.ensure_one()
        bail = self.bail_id
        bail.lettrer()
        montant = round(-bail.solde, 2)
        if montant <= 0:
            return 0.0
        banque = self.env["coproerp.locatif.dossier"].actif().journal("banque").default_account_id
        self._ecriture("banque", date, libelle, [
            ("locataires", bail.locataire_id, montant, 0.0, libelle),
            (banque, None, 0.0, montant, libelle),
        ])
        bail.lettrer()
        return montant

    def _controler_fonds_proprietaire(self):
        """Le compte du propriétaire ne peut pas devenir débiteur des fonds réellement encaissés."""
        situation = self.env["coproerp.locatif.mandat"].situation_proprietaire(self.proprietaire_id)
        if situation["solde"] - situation["impayes"] < -0.004:
            raise UserError(
                "Le compte de %s ne suffit pas à couvrir cette opération (solde %s, dont %s de loyers non encaissés) : "
                "demandez-lui de verser la somme manquante avant de restituer le dépôt."
                % (self.proprietaire_id.name, _euros(situation["solde"]), _euros(situation["impayes"])))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_arreter(self):
        """Arrête le décompte : dernier loyer, retenues, dépôt imputé sur ce qui reste dû."""
        Echeance = self.env["coproerp.locatif.echeance"]
        for sortie in self.filtered(lambda s: s.etat == "brouillon"):
            bail = sortie.bail_id
            sans_justificatif = sortie.retenue_ids.filtered(lambda r: not r.justificatif)
            if sans_justificatif:
                raise UserError("Chaque retenue doit être justifiée (devis, facture, constat) : %s."
                                % ", ".join(sans_justificatif.mapped("libelle")))
            if sortie.name == "/":
                sortie.name = self.env["ir.sequence"].next_by_code("coproerp.locatif.sortie") or "/"
            if bail.etat == "en_cours":
                if not bail.date_sortie:
                    # Le loyer court jusqu'à la fin du préavis, même si le locataire part avant.
                    bail.date_sortie = max(sortie.date_remise_cles, sortie.date_fin_preavis or sortie.date_remise_cles)
                bail.action_terminer()
            bail.lettrer()
            avis_ouverts = bail.echeance_ids.filtered(lambda e: not e.annulee and e.type_echeance != "depot")
            sortie.impayes = round(sum(m for m in avis_ouverts.mapped("montant_restant") if m > 0), 2)
            if sortie.retenue_ids:
                sortie.avis_retenues_id = Echeance._creer(
                    bail, "sortie", sortie.date_remise_cles, sortie.date_remise_cles, sortie.date_remise_cles,
                    [("autre", "%s (%s)" % (r.libelle, r.justificatif), r.montant) for r in sortie.retenue_ids])
            sortie._transferer_depot(sortie.depot_verse - sortie.reserve, sortie.date_remise_cles,
                                     "%s – Dépôt de garantie imputé sur le décompte de sortie" % sortie.name)
            bail.lettrer()
            if not sortie.depot_conserve:
                sortie._controler_fonds_proprietaire()
            sortie.write({"solde_final": round(-bail.solde, 2), "etat": "arrete"})
        return True

    @api.model
    def mois_commences(self, limite, jour):
        """Nombre de périodes mensuelles commencées entre la date limite et le jour donné."""
        mois = 0
        while limite and jour and limite + relativedelta(months=mois) < jour:
            mois += 1
        return mois

    def action_restituer(self, date_restitution=None):
        for sortie in self.filtered(lambda s: s.etat == "arrete"):
            jour = date_restitution or fields.Date.context_today(self)
            bail = sortie.bail_id
            mois, majoration = 0, 0.0
            if sortie.regime_legal and sortie.nouvelle_adresse and round(-bail.solde, 2) > 0:
                mois = self.mois_commences(sortie.date_limite, jour)
                majoration = round(0.10 * bail.loyer_hc * mois, 2)
            if majoration:
                libelle = "%s – Majoration pour restitution tardive du dépôt (10 %% du loyer × %d mois)" % (
                    sortie.name, mois)
                sortie._ecriture("od", jour, libelle, [
                    ("proprietaires", bail.proprietaire_id, majoration, 0.0, libelle),
                    ("locataires", bail.locataire_id, 0.0, majoration, libelle),
                ])
            montant = sortie._rembourser(jour, "%s – Restitution du dépôt de garantie à %s" % (
                sortie.name, bail.locataire_id.name))
            if majoration:
                sortie._controler_fonds_proprietaire()
            sortie.write({"date_restitution": jour, "mois_retard": mois, "majoration": majoration,
                          "montant_restitue": montant, "etat": "restitue",
                          "reserve_soldee": not sortie.reserve})
        return True

    def action_solder_reserve(self, date_versement=None):
        """Après l'approbation des comptes de la copropriété : charges définitives et solde de la provision."""
        for sortie in self.filtered(lambda s: s.etat == "restitue" and s.reserve and not s.reserve_soldee):
            if not sortie.date_approbation:
                raise UserError("Indiquez la date d'approbation des comptes de la copropriété.")
            jour = date_versement or fields.Date.context_today(self)
            bail = sortie.bail_id
            if sortie.charges_definitives:
                self.env["coproerp.locatif.echeance"]._creer(
                    bail, "sortie", sortie.date_remise_cles, sortie.date_remise_cles, sortie.date_approbation,
                    [("charges", "Charges définitives après approbation des comptes de la copropriété",
                      sortie.charges_definitives)])
            sortie._transferer_depot(sortie.reserve, jour, "%s – Solde de la provision pour charges" % sortie.name)
            montant = sortie._rembourser(jour, "%s – Solde du dépôt de garantie à %s" % (
                sortie.name, bail.locataire_id.name))
            if not sortie.depot_conserve:
                sortie._controler_fonds_proprietaire()
            sortie.write({"reserve_soldee": True, "montant_restitue_reserve": montant})
        return True

    def action_annuler(self):
        """Annule un décompte arrêté mais pas encore restitué."""
        for sortie in self.filtered(lambda s: s.etat == "arrete"):
            moves = sortie.move_ids.sudo()
            moves.line_ids.remove_move_reconcile()
            moves._reverse_moves([{"date": m.date, "ref": "Annulation %s" % sortie.name} for m in moves],
                                 cancel=True)
            bail = sortie.bail_id
            bail.echeance_ids._maj_paiement()
            if sortie.avis_retenues_id:
                sortie.avis_retenues_id.move_id.sudo().line_ids.remove_move_reconcile()
                sortie.avis_retenues_id._maj_paiement()
                sortie.avis_retenues_id.action_annuler()
            bail.lettrer()
            sortie.etat = "annule"
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_locatif_sortie.action_report_sortie").report_action(self)

    def unlink(self):
        if any(s.etat not in ("brouillon", "annule") for s in self):
            raise UserError("Un décompte arrêté ne se supprime pas : annulez-le.")
        return super().unlink()


class Retenue(models.Model):
    _name = "coproerp.locatif.sortie.retenue"
    _description = "Retenue sur le dépôt de garantie"
    _order = "id"

    sortie_id = fields.Many2one("coproerp.locatif.sortie", required=True, ondelete="cascade")
    nature = fields.Selection(NATURES_RETENUE, string="Nature", required=True, default="reparations")
    libelle = fields.Char(string="Objet", required=True)
    justificatif = fields.Char(string="Justificatif", help="Devis, facture, constat… (obligatoire)")
    montant = fields.Float(string="Montant", digits=(16, 2), required=True)

    @api.constrains("montant")
    def _check_montant(self):
        for retenue in self:
            if retenue.montant <= 0:
                raise ValidationError("Le montant d'une retenue doit être positif.")
