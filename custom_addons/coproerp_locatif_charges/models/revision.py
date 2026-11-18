from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.coproerp_locatif.models.bail import HABITATION


class RevisionLoyer(models.Model):
    """Révision annuelle du loyer selon l'indice prévu au bail."""

    _name = "coproerp.locatif.revision"
    _description = "Révision du loyer"
    _inherit = ["mail.thread"]
    _order = "date_revision desc, id desc"

    name = fields.Char(string="Révision", compute="_compute_name", store=True)
    bail_id = fields.Many2one("coproerp.locatif.bail", string="Bail", required=True, index=True, ondelete="cascade")
    locataire_id = fields.Many2one(related="bail_id.locataire_id", store=True, string="Locataire")
    proprietaire_id = fields.Many2one(related="bail_id.proprietaire_id", store=True, string="Propriétaire")
    type_indice = fields.Selection(related="bail_id.indice", string="Indice")
    date_revision = fields.Date(string="Date de révision prévue au bail", required=True)
    date_effet = fields.Date(string="Nouveau loyer applicable le", readonly=True)
    trimestre = fields.Char(string="Trimestre de référence", readonly=True)
    annee_ancienne = fields.Integer(string="Année de l'indice de référence", readonly=True)
    valeur_ancienne = fields.Float(string="Indice de référence", digits=(8, 2), readonly=True)
    annee_nouvelle = fields.Integer(string="Année du nouvel indice", readonly=True)
    valeur_nouvelle = fields.Float(string="Nouvel indice", digits=(8, 2), readonly=True)
    loyer_ancien = fields.Float(string="Loyer actuel (hors charges)", digits=(16, 2), readonly=True)
    loyer_nouveau = fields.Float(string="Nouveau loyer (hors charges)", digits=(16, 2), readonly=True)
    variation = fields.Float(string="Variation (%)", digits=(6, 2), readonly=True)
    rappel_id = fields.Many2one("coproerp.locatif.echeance", string="Avis de rappel", readonly=True)
    etat = fields.Selection([("proposee", "À appliquer"), ("appliquee", "Appliquée"), ("abandonnee", "Abandonnée")],
                            string="État", default="proposee", required=True, tracking=True)

    @api.depends("bail_id", "date_revision")
    def _compute_name(self):
        for revision in self:
            revision.name = "Révision %s – %s" % (
                revision.bail_id.name or "", revision.date_revision.strftime("%d/%m/%Y") if revision.date_revision else "")

    # ------------------------------------------------------------------
    @api.model
    def preparer(self, bail):
        """Calcule la révision de la prochaine date anniversaire du bail."""
        if bail.etat != "en_cours":
            raise UserError("Seul un bail en cours peut être révisé.")
        if bail.indice == "aucun":
            raise UserError("Le bail %s ne prévoit pas de révision." % bail.name)
        if not (bail.indice_trimestre and bail.indice_annee):
            raise UserError("Indiquez sur le bail %s le trimestre et l'année de l'indice de référence." % bail.name)
        date_revision = bail.date_prochaine_revision
        existante = self.search([("bail_id", "=", bail.id), ("date_revision", "=", date_revision),
                                 ("etat", "!=", "abandonnee")], limit=1)
        if existante:
            return existante
        Indice = self.env["coproerp.locatif.indice"]
        ancien = bail.valeur_indice or Indice.trouver(bail.indice, bail.indice_annee, bail.indice_trimestre).valeur
        if not ancien:
            raise UserError("L'indice de référence %s T%s %s n'est pas dans la table des indices."
                            % (bail.indice.upper(), bail.indice_trimestre, bail.indice_annee))
        nouveau = Indice.trouver(bail.indice, bail.indice_annee + 1, bail.indice_trimestre)
        if not nouveau:
            raise UserError("L'indice %s du %s trimestre %d n'est pas encore publié ou pas encore saisi dans la table "
                            "des indices." % (bail.indice.upper(), "1er" if bail.indice_trimestre == "1"
                                              else "%se" % bail.indice_trimestre, bail.indice_annee + 1))
        loyer = round(bail.loyer_hc * nouveau.valeur / ancien, 2)
        return self.create({
            "bail_id": bail.id, "date_revision": date_revision, "trimestre": "T%s" % bail.indice_trimestre,
            "annee_ancienne": bail.indice_annee, "valeur_ancienne": ancien,
            "annee_nouvelle": bail.indice_annee + 1, "valeur_nouvelle": nouveau.valeur,
            "loyer_ancien": bail.loyer_hc, "loyer_nouveau": loyer,
            "variation": round((nouveau.valeur / ancien - 1) * 100, 2),
        })

    @api.model
    def preparer_revisions(self, horizon=30):
        """Prépare les révisions dont la date tombe dans les « horizon » jours (tâche quotidienne)."""
        limite = fields.Date.context_today(self) + timedelta(days=horizon)
        preparees = self
        for bail in self.env["coproerp.locatif.bail"].search([("etat", "=", "en_cours"), ("indice", "!=", "aucun"),
                                                              ("indice_trimestre", "!=", False)]):
            if bail.date_prochaine_revision and bail.date_prochaine_revision <= limite:
                try:
                    with self.env.cr.savepoint():
                        preparees |= self.preparer(bail)
                except UserError:
                    continue  # indice pas encore publié : on réessaiera
        return preparees

    def action_appliquer(self):
        aujourdhui = fields.Date.context_today(self)
        for revision in self.filtered(lambda r: r.etat == "proposee"):
            bail = revision.bail_id
            habitation = bail.type_bail in HABITATION or bail.type_bail in ("stationnement", "code_civil")
            if habitation and aujourdhui > revision.date_revision + relativedelta(years=1, days=-1):
                raise UserError(
                    "La révision du %s n'a pas été demandée dans l'année : elle est perdue pour le bailleur "
                    "(art. 17-1 de la loi du 6 juillet 1989). Abandonnez-la." % revision.date_revision.strftime("%d/%m/%Y"))
            # Logement : pas d'effet rétroactif, le nouveau loyer s'applique à compter de la demande.
            date_effet = max(revision.date_revision, aujourdhui) if habitation else revision.date_revision
            ecart = round(revision.loyer_nouveau - revision.loyer_ancien, 2)
            bail.write({"loyer_hc": revision.loyer_nouveau, "indice_annee": revision.annee_nouvelle,
                        "valeur_indice": revision.valeur_nouvelle, "date_derniere_revision": revision.date_revision,
                        "trimestre_reference": "%s %s" % (revision.trimestre, revision.annee_nouvelle)})
            revision.write({"etat": "appliquee", "date_effet": date_effet})
            revision._emettre_rappel(date_effet, ecart)
        return True

    def _emettre_rappel(self, date_effet, ecart):
        """Avis complémentaire pour les loyers déjà appelés depuis la date d'effet."""
        self.ensure_one()
        bail = self.bail_id
        if not ecart:
            return
        mois = 3 if bail.periodicite == "trimestriel" else 1
        montant, fin = 0.0, None
        for avis in bail.echeance_ids.filtered(lambda e: e.type_echeance == "loyer" and not e.annulee
                                               and e.periode_fin >= date_effet):
            debut = max(avis.periode_debut, date_effet)
            montant += ecart * mois * bail._prorata(debut, avis.periode_fin)
            fin = max(fin, avis.periode_fin) if fin else avis.periode_fin
        montant = round(montant, 2)
        if not montant:
            return
        lignes = [("loyer", "Révision du loyer (%+.2f € par mois)" % ecart, montant)]
        if bail.tva:
            lignes.append(("tva", "TVA %g %%" % bail.taux_tva, montant * bail.taux_tva / 100))
        self.rappel_id = self.env["coproerp.locatif.echeance"]._creer(
            bail, "revision", date_effet, fin, fields.Date.context_today(self), lignes)

    def action_abandonner(self):
        self.filtered(lambda r: r.etat == "proposee").write({"etat": "abandonnee"})
        return True

    def action_imprimer(self):
        return self.env.ref("coproerp_locatif_charges.action_report_revision").report_action(self)
