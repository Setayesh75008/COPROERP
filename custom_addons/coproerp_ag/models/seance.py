"""Tenue de l'assemblée : feuille de présence, votes, majorités, procès-verbal."""

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

MAX_MANDATS = 3          # art. 22 de la loi du 10 juillet 1965
SEUIL_MANDATS = 0.10     # … sauf si mandataire + mandants <= 10 % des voix du syndicat

STATUTS = [
    ("absent", "Absent (défaillant)"),
    ("present", "Présent"),
    ("represente", "Représenté"),
    ("correspondance", "Vote par correspondance"),
]
SENS = [
    ("pour", "Pour"),
    ("contre", "Contre"),
    ("abstention", "Abstention"),
    ("defaillant", "Ne prend pas part au vote"),
]
RESULTATS = [
    ("non_vote", "Non votée"),
    ("adoptee", "Adoptée"),
    ("rejetee", "Rejetée"),
    ("second_vote", "Second vote"),
]


# ----------------------------------------------------------------------
# Nombres en lettres (préambule du procès-verbal)
# ----------------------------------------------------------------------
_UNITES = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze",
           "douze", "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
_DIZAINES = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _moins_de_cent(n):
    if n < 20:
        return _UNITES[n]
    dizaine, unite = divmod(n, 10)
    if dizaine in (7, 9):
        base = "soixante" if dizaine == 7 else "quatre-vingt"
        reste = 10 + unite
        liaison = " et " if (dizaine == 7 and unite == 1) else "-"
        return base + liaison + _UNITES[reste]
    if dizaine == 8:
        return "quatre-vingts" if unite == 0 else "quatre-vingt-" + _UNITES[unite]
    base = _DIZAINES[dizaine]
    if unite == 0:
        return base
    if unite == 1:
        return base + " et un"
    return base + "-" + _UNITES[unite]


def en_lettres(n):
    """Entier de 0 à 9 999 en toutes lettres (orthographe traditionnelle)."""
    if n < 100:
        return _moins_de_cent(n)
    if n < 1000:
        centaines, reste = divmod(n, 100)
        tete = "cent" if centaines == 1 else _UNITES[centaines] + " cent"
        if reste == 0:
            return tete + ("s" if centaines > 1 else "")
        return tete + " " + _moins_de_cent(reste)
    milliers, reste = divmod(n, 1000)
    tete = "mille" if milliers == 1 else en_lettres(milliers) + " mille"
    return tete if reste == 0 else tete + " " + en_lettres(reste)


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]


def preambule_date(d, heure):
    """« L'an deux mille vingt-sept, le vingt-huit avril, à dix-sept heures trente »"""
    heures = int(heure or 0)
    minutes = int(round(((heure or 0) - heures) * 60))
    jour = "premier" if d.day == 1 else en_lettres(d.day)
    texte_heure = "%s heure%s" % (en_lettres(heures) if heures != 1 else "une", "s" if heures > 1 else "")
    if minutes:
        texte_heure += " " + en_lettres(minutes)
    return "L'an %s, le %s %s, à %s" % (en_lettres(d.year), jour, MOIS[d.month - 1], texte_heure)


# ----------------------------------------------------------------------
class AssembleeGenerale(models.Model):
    _inherit = "coproerp.ag"

    presence_ids = fields.One2many("coproerp.ag.presence", "ag_id", string="Feuille de présence")
    president = fields.Char(string="Président de séance")
    scrutateurs = fields.Char(string="Scrutateur(s)")
    secretaire = fields.Char(string="Secrétaire de séance")
    heure_ouverture = fields.Float(string="Ouverture de la séance")
    heure_cloture = fields.Float(string="Clôture de la séance")
    total_voix_effectif = fields.Integer(
        string="Voix de tous les copropriétaires", compute="_compute_presence",
        help="Total des voix, après réduction éventuelle des voix d'un copropriétaire détenant plus de la "
             "moitié des parties communes (art. 22).",
    )
    nombre_membres = fields.Integer(string="Membres du syndicat", compute="_compute_presence")
    nombre_participants = fields.Integer(string="Présents, représentés ou votant par correspondance",
                                         compute="_compute_presence")
    voix_participants = fields.Integer(string="Voix présentes, représentées ou par correspondance",
                                       compute="_compute_presence")
    controle_mandats = fields.Text(string="Contrôle des mandats", compute="_compute_presence")
    date_limite_notification_pv = fields.Date(
        string="Notification du PV au plus tard le", compute="_compute_date_limite_pv",
        help="Le procès-verbal est notifié aux opposants et défaillants dans le délai d'un mois à compter de "
             "la tenue de l'assemblée (art. 42 de la loi).",
    )

    @api.depends("presence_ids.statut", "presence_ids.voix", "presence_ids.mandataire_id")
    def _compute_presence(self):
        for ag in self:
            lignes = ag.presence_ids
            total = sum(lignes.mapped("voix"))
            reduction = sum(l.voix - l.voix_effectives for l in lignes)
            participants = lignes.filtered(lambda l: l.statut != "absent")
            ag.total_voix_effectif = total - reduction
            ag.nombre_membres = len(lignes)
            ag.nombre_participants = len(participants)
            ag.voix_participants = sum(participants.mapped("voix_effectives"))
            ag.controle_mandats = "\n".join(ag._anomalies_mandats()) or False

    @api.depends("date_ag")
    def _compute_date_limite_pv(self):
        for ag in self:
            ag.date_limite_notification_pv = ag.date_ag + relativedelta(months=1) if ag.date_ag else False

    def _anomalies_mandats(self):
        """Contrôle de l'article 22 : nombre de mandats et personnes exclues."""
        self.ensure_one()
        anomalies = []
        total = sum(self.presence_ids.mapped("voix")) or 1
        copro = self.copropriete_id.sudo()
        exclus = copro.syndic_id | copro.gestionnaire_id.partner_id
        par_mandataire = {}
        for ligne in self.presence_ids.filtered(lambda l: l.statut == "represente"):
            if not ligne.mandataire_id:
                anomalies.append("%s est représenté sans mandataire indiqué." % ligne.personne_id.name)
                continue
            par_mandataire.setdefault(ligne.mandataire_id, self.env["coproerp.ag.presence"])
            par_mandataire[ligne.mandataire_id] |= ligne
        for mandataire, mandants in par_mandataire.items():
            if mandataire in exclus or (mandataire.commercial_partner_id in exclus.commercial_partner_id):
                anomalies.append("%s ne peut pas recevoir de mandat (syndic ou son préposé, art. 22)." % mandataire.name)
            if len(mandants) > MAX_MANDATS:
                propres = self.presence_ids.filtered(lambda l: l.personne_id == mandataire)
                voix = sum(mandants.mapped("voix")) + sum(propres.mapped("voix"))
                if voix > SEUIL_MANDATS * total:
                    anomalies.append(
                        "%s détient %d mandats représentant, avec ses propres voix, %d voix sur %d (plus de 10 %%) : "
                        "les mandats au-delà du troisième ne peuvent pas être pris en compte (art. 22)."
                        % (mandataire.name, len(mandants), voix, total))
        for ligne in self.presence_ids.filtered(lambda l: l.statut == "represente" and l.mandataire_id == l.personne_id):
            anomalies.append("%s ne peut pas être son propre mandataire." % ligne.personne_id.name)
        return anomalies

    def action_ouvrir_feuille_presence(self):
        """Crée la feuille de présence à partir des convocations."""
        for ag in self:
            if ag.etat != "convoquee":
                raise UserError("La feuille de présence s'ouvre lorsque l'assemblée a été convoquée.")
            existants = ag.presence_ids.personne_id
            ag.write({"presence_ids": [Command.create({
                "personne_id": c.personne_id.id,
                "voix": c.voix,
                "lot_ids": [Command.set(c.lot_ids.ids)],
            }) for c in ag.convocation_ids if c.personne_id not in existants]})
        return True

    def action_cloturer_seance(self):
        for ag in self:
            anomalies = ag._anomalies_mandats()
            if anomalies:
                raise UserError("Mandats à corriger avant de clôturer :\n- " + "\n- ".join(anomalies))
            non_votees = ag.resolutions_votees().filtered(lambda r: r.resultat == "non_vote")
            if non_votees:
                raise UserError("Résolution(s) non votée(s) : %s." % ", ".join(non_votees.mapped("numero")))
            en_attente = ag.resolution_ids.filtered(lambda r: r.resultat == "second_vote" and r.resultat2 == "non_vote")
            if en_attente:
                raise UserError("Second vote à saisir pour la ou les résolution(s) : %s."
                                % ", ".join(en_attente.mapped("numero")))
            ag.etat = "tenue"
        return True

    def action_rouvrir_seance(self):
        self.filtered(lambda a: a.etat == "tenue").write({"etat": "convoquee"})
        return True

    def action_imprimer_feuille_presence(self):
        return self.env.ref("coproerp_ag.action_report_feuille_presence").report_action(self)

    def action_imprimer_pv(self):
        return self.env.ref("coproerp_ag.action_report_pv").report_action(self)

    def action_imprimer_pv_notifications(self):
        self.ensure_one()
        lignes = self.presence_ids.filtered("pv_a_notifier")
        if not lignes:
            raise UserError("Aucun opposant ni défaillant : le procès-verbal n'a pas à être notifié.")
        return self.env.ref("coproerp_ag.action_report_pv_notification").report_action(lignes)

    def action_suivi_notifications_pv(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Notification du procès-verbal",
            "res_model": "coproerp.ag.presence",
            "view_mode": "list",
            "views": [(self.env.ref("coproerp_ag.view_ag_presence_notification_list").id, "list")],
            "domain": [("ag_id", "=", self.id), ("pv_a_notifier", "=", True)],
        }

    def adresse_lieu_ligne(self):
        self.ensure_one()
        return ", ".join(l.strip() for l in (self.lieu_adresse or "").splitlines() if l.strip())

    def preambule(self):
        self.ensure_one()
        return preambule_date(self.date_ag, self.heure_ouverture or self.heure)

    def heure_texte_champ(self, champ):
        self.ensure_one()
        valeur = self[champ] or 0.0
        heures = int(valeur)
        return "%dh%02d" % (heures, int(round((valeur - heures) * 60)))

    def presences_par_statut(self, statuts):
        self.ensure_one()
        return self.presence_ids.filtered(lambda l: l.statut in statuts).sorted(lambda l: l.personne_id.name or "")


class Presence(models.Model):
    _name = "coproerp.ag.presence"
    _description = "Ligne de la feuille de présence"
    _order = "ag_id, personne_id"

    ag_id = fields.Many2one("coproerp.ag", string="Assemblée", required=True, ondelete="cascade", index=True)
    personne_id = fields.Many2one("res.partner", string="Copropriétaire", required=True)
    lot_ids = fields.Many2many(
        "coproerp.lot", "coproerp_ag_presence_lot_rel", "presence_id", "lot_id", string="Lots")
    voix = fields.Integer(string="Voix")
    voix_effectives = fields.Integer(
        string="Voix prises en compte", compute="_compute_voix_effectives", store=True,
        help="Un copropriétaire détenant plus de la moitié des voix voit celles-ci réduites à la somme des voix "
             "des autres copropriétaires (art. 22 de la loi).",
    )
    statut = fields.Selection(STATUTS, string="Participation", required=True, default="absent")
    mandataire_id = fields.Many2one("res.partner", string="Représenté par")
    heure_arrivee = fields.Float(string="Arrivée")
    vote_correspondance_ids = fields.One2many(
        "coproerp.ag.vote.correspondance", "presence_id", string="Votes par correspondance")
    # Notification du procès-verbal
    pv_a_notifier = fields.Boolean(string="PV à notifier", compute="_compute_pv_a_notifier", store=True)
    pv_qualite = fields.Char(string="Qualité", compute="_compute_pv_a_notifier", store=True)
    pv_mode_envoi = fields.Selection(
        [("lre", "Lettre recommandée électronique"), ("lrar", "Lettre recommandée avec AR")],
        string="Notification du PV")
    pv_numero_envoi = fields.Char(string="N° de recommandé (PV)")
    pv_date_presentation = fields.Date(string="Première présentation du PV")
    pv_date_limite_recours = fields.Date(
        string="Fin du délai de recours", compute="_compute_recours", store=True,
        help="Deux mois à compter de la notification du procès-verbal (art. 42 de la loi).",
    )

    @api.depends("voix", "ag_id.presence_ids.voix")
    def _compute_voix_effectives(self):
        for ligne in self:
            total = sum(ligne.ag_id.presence_ids.mapped("voix"))
            autres = total - ligne.voix
            ligne.voix_effectives = min(ligne.voix, autres) if ligne.voix * 2 > total and total else ligne.voix

    @api.depends("statut", "ag_id.resolution_ids.vote_ids.sens", "ag_id.resolution_ids.resultat",
                 "ag_id.resolution_ids.resultat2")
    def _compute_pv_a_notifier(self):
        for ligne in self:
            if ligne.statut == "absent":
                ligne.pv_a_notifier, ligne.pv_qualite = True, "Défaillant"
                continue
            opposant = defaillant = False
            for resolution in ligne.ag_id.resolution_ids:
                decision = resolution.decision_finale()
                if decision not in ("adoptee", "rejetee"):
                    continue
                tour = 2 if resolution.resultat == "second_vote" else 1
                vote = resolution.vote_ids.filtered(lambda v: v.presence_id == ligne and v.tour == tour)[:1]
                if not vote:
                    continue
                if vote.sens == "defaillant":
                    defaillant = True
                elif (decision == "adoptee" and vote.sens == "contre") or (decision == "rejetee" and vote.sens == "pour"):
                    opposant = True
            ligne.pv_a_notifier = opposant or defaillant
            ligne.pv_qualite = "Opposant" if opposant else ("Défaillant" if defaillant else False)

    @api.depends("pv_date_presentation")
    def _compute_recours(self):
        for ligne in self:
            ligne.pv_date_limite_recours = (
                ligne.pv_date_presentation + relativedelta(months=2) if ligne.pv_date_presentation else False)

    @api.constrains("statut", "mandataire_id")
    def _check_mandataire(self):
        for ligne in self:
            if ligne.statut != "represente" and ligne.mandataire_id:
                raise ValidationError("Le mandataire ne s'indique que pour un copropriétaire représenté.")

    @api.onchange("statut")
    def _onchange_statut(self):
        if self.statut != "represente":
            self.mandataire_id = False

    def lots_texte(self):
        self.ensure_one()
        return ", ".join(self.lot_ids.mapped("numero"))

    def action_saisir_formulaire_vpc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Vote par correspondance – %s" % self.personne_id.name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("coproerp_ag.view_ag_presence_vpc_form").id,
            "target": "new",
        }

    def statut_libelle(self):
        self.ensure_one()
        return dict(STATUTS)[self.statut]


class VoteCorrespondance(models.Model):
    """Sens du vote indiqué sur le formulaire de vote par correspondance."""

    _name = "coproerp.ag.vote.correspondance"
    _description = "Vote par correspondance"
    _order = "resolution_id, tour"

    presence_id = fields.Many2one("coproerp.ag.presence", required=True, ondelete="cascade", index=True)
    ag_id = fields.Many2one(related="presence_id.ag_id", store=True)
    resolution_id = fields.Many2one(
        "coproerp.ag.resolution", string="Résolution", required=True, ondelete="cascade",
        domain="[('ag_id', '=', ag_id), ('majorite', 'not in', ('rubrique', 'information'))]",
    )
    tour = fields.Selection([("1", "Vote"), ("2", "Second vote")], string="Vote", required=True, default="1")
    sens = fields.Selection(SENS[:3], string="Sens", required=True)

    _unique_vote = models.Constraint(
        "UNIQUE(presence_id, resolution_id, tour)", "Un seul sens de vote par résolution.")


class Vote(models.Model):
    _name = "coproerp.ag.vote"
    _description = "Vote d'un copropriétaire sur une résolution"
    _order = "resolution_id, tour, personne_id"

    resolution_id = fields.Many2one("coproerp.ag.resolution", required=True, ondelete="cascade", index=True)
    tour = fields.Integer(string="Tour", default=1, required=True)
    presence_id = fields.Many2one("coproerp.ag.presence", required=True, ondelete="cascade")
    personne_id = fields.Many2one(related="presence_id.personne_id", store=True, string="Copropriétaire")
    origine = fields.Selection(related="presence_id.statut", string="Participation")
    voix = fields.Integer(related="presence_id.voix_effectives", string="Voix")
    sens = fields.Selection(SENS, string="Sens du vote", required=True, default="pour")
    note = fields.Char(string="Observation")


class Resolution(models.Model):
    _inherit = "coproerp.ag.resolution"

    texte_adopte = fields.Text(string="Texte soumis au vote", help="Texte définitif, éventuellement amendé en séance.")
    amendee = fields.Boolean(
        string="Amendée en séance",
        help="Les copropriétaires ayant voté favorablement par correspondance sont alors assimilés à des "
             "défaillants pour cette résolution (art. 17-1 A de la loi).",
    )
    vote_ids = fields.One2many("coproerp.ag.vote", "resolution_id", string="Votes")
    vote1_ids = fields.One2many("coproerp.ag.vote", "resolution_id", domain=[("tour", "=", 1)], string="Vote")
    vote2_ids = fields.One2many("coproerp.ag.vote", "resolution_id", domain=[("tour", "=", 2)], string="Second vote")
    pour = fields.Integer(compute="_compute_resultat", store=True, string="Pour")
    contre = fields.Integer(compute="_compute_resultat", store=True, string="Contre")
    abstention = fields.Integer(compute="_compute_resultat", store=True, string="Abstentions")
    resultat = fields.Selection(RESULTATS, compute="_compute_resultat", store=True, string="Résultat")
    pour2 = fields.Integer(compute="_compute_resultat", store=True, string="Pour (2nd vote)")
    contre2 = fields.Integer(compute="_compute_resultat", store=True, string="Contre (2nd vote)")
    abstention2 = fields.Integer(compute="_compute_resultat", store=True, string="Abstentions (2nd vote)")
    resultat2 = fields.Selection(RESULTATS, compute="_compute_resultat", store=True, string="Résultat du 2nd vote")
    compte_rendu = fields.Text(string="Compte rendu", help="Pour les points d'information et les questions diverses.")
    reserves = fields.Text(string="Réserves", help="Réserves formulées sur la régularité des délibérations (art. 17 du décret).")

    @api.depends("vote_ids.sens", "vote_ids.voix", "vote_ids.tour", "majorite",
                 "ag_id.presence_ids.voix_effectives")
    def _compute_resultat(self):
        for resolution in self:
            r1 = resolution._resultat_tour(1)
            r2 = resolution._resultat_tour(2) if r1["resultat"] == "second_vote" else None
            resolution.update({
                "pour": r1["pour"], "contre": r1["contre"], "abstention": r1["abstention"],
                "resultat": r1["resultat"],
                "pour2": r2["pour"] if r2 else 0, "contre2": r2["contre"] if r2 else 0,
                "abstention2": r2["abstention"] if r2 else 0,
                "resultat2": r2["resultat"] if r2 else False,
            })

    def majorite_tour(self, tour):
        self.ensure_one()
        if tour == 1:
            return self.majorite
        return {"art25": "art24", "art26": "art25"}.get(self.majorite, self.majorite)

    def _resultat_tour(self, tour):
        votes = self.vote_ids.filtered(lambda v: v.tour == tour)
        somme = {s: sum(votes.filtered(lambda v, s=s: v.sens == s).mapped("voix")) for s in ("pour", "contre", "abstention")}
        res = dict(somme, resultat="non_vote")
        if self.majorite in ("rubrique", "information") or not votes:
            return res
        ag = self.ag_id
        total = ag.total_voix_effectif
        majorite = self.majorite_tour(tour)
        pour, contre = somme["pour"], somme["contre"]
        if majorite == "art24":
            adoptee = pour > contre
        elif majorite == "art25":
            adoptee = pour * 2 > total
            if not adoptee and tour == 1 and pour * 3 >= total:
                res["resultat"] = "second_vote"
                return res
        elif majorite == "art26":
            membres_pour = len(votes.filtered(lambda v: v.sens == "pour"))
            adoptee = membres_pour * 2 > ag.nombre_membres and pour * 3 >= total * 2
            participants = len(votes.filtered(lambda v: v.sens != "defaillant"))
            if not adoptee and tour == 1 and membres_pour * 2 >= participants and pour * 3 >= total:
                res["resultat"] = "second_vote"
                return res
        else:  # unanimité de tous les copropriétaires
            adoptee = pour == total and not contre and not somme["abstention"]
        res["resultat"] = "adoptee" if adoptee else "rejetee"
        return res

    def decision_finale(self):
        self.ensure_one()
        if self.resultat == "second_vote":
            return self.resultat2 or "non_vote"
        return self.resultat or "non_vote"

    def action_initialiser_vote(self, tour=1):
        """Crée une ligne de vote par participant : « pour » par défaut pour les présents et
        représentés, sens du formulaire pour les votes par correspondance."""
        for resolution in self:
            ag = resolution.ag_id
            if resolution.majorite in ("rubrique", "information"):
                raise UserError("Ce point n'est pas soumis au vote.")
            if ag.etat != "convoquee":
                raise UserError("Les votes se saisissent pendant la séance (assemblée convoquée, non clôturée).")
            if tour == 2 and resolution.resultat != "second_vote":
                raise UserError("Le second vote n'est possible que si la passerelle est ouverte.")
            if not ag.presence_ids:
                raise UserError("Ouvrez d'abord la feuille de présence.")
            resolution.vote_ids.filtered(lambda v: v.tour == tour).unlink()
            commandes = []
            for presence in ag.presence_ids.filtered(lambda p: p.statut != "absent"):
                sens, note = "pour", False
                if presence.statut == "correspondance":
                    formulaire = presence.vote_correspondance_ids.filtered(
                        lambda v: v.resolution_id == resolution and v.tour == str(tour))[:1]
                    if not formulaire:
                        sens, note = "defaillant", "Pas de sens de vote exprimé sur le formulaire"
                    elif resolution.amendee and formulaire.sens == "pour":
                        sens, note = "defaillant", "Vote favorable par correspondance sur une résolution amendée"
                    else:
                        sens = formulaire.sens
                commandes.append(Command.create({"tour": tour, "presence_id": presence.id, "sens": sens, "note": note}))
            resolution.write({"vote_ids": commandes})
            if not resolution.texte_adopte:
                resolution.texte_adopte = resolution.texte
        return True

    def action_initialiser_second_vote(self):
        return self.action_initialiser_vote(tour=2)

    def action_ouvrir_vote(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Vote – résolution %s" % (self.numero or ""),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("coproerp_ag.view_ag_resolution_vote_form").id,
            "target": "new",
        }

    # -- textes du procès-verbal ------------------------------------------
    def votants(self, tour, sens):
        self.ensure_one()
        return self.vote_ids.filtered(lambda v: v.tour == tour and v.sens == sens).sorted(
            lambda v: v.personne_id.name or "")

    def phrase_resultat(self, tour=1):
        self.ensure_one()
        resultat = self.resultat if tour == 1 else self.resultat2
        majorite = self.majorite_tour(tour)
        libelles = {
            "art24": "à la majorité des voix exprimées des copropriétaires présents, représentés ou ayant voté par "
                     "correspondance (article 24)",
            "art25": "à la majorité des voix de tous les copropriétaires (article 25)",
            "art26": "à la majorité des membres du syndicat représentant au moins les deux tiers des voix (article 26)",
            "unanimite": "à l'unanimité des voix de tous les copropriétaires",
        }
        if resultat == "second_vote":
            if self.majorite == "art25":
                return ("Le projet n'a pas recueilli la majorité de l'article 25 mais au moins le tiers des voix de tous "
                        "les copropriétaires : l'assemblée procède immédiatement à un second vote à la majorité de "
                        "l'article 24 (article 25-1).")
            return ("Le projet n'a pas recueilli la majorité de l'article 26 mais l'approbation de la moitié des membres "
                    "présents, représentés ou ayant voté par correspondance, représentant au moins le tiers des voix : "
                    "l'assemblée procède immédiatement à un second vote à la majorité de l'article 25.")
        if resultat == "adoptee":
            unanime = not (self.contre if tour == 1 else self.contre2) and not (
                self.abstention if tour == 1 else self.abstention2)
            return "Cette résolution est ADOPTÉE %s%s." % (libelles.get(majorite, ""), " (à l'unanimité des votants)" if unanime and majorite != "unanimite" else "")
        if resultat == "rejetee":
            return "Cette résolution est REJETÉE, faute d'avoir recueilli la majorité requise %s." % libelles.get(majorite, "")
        return "Résolution non votée."
