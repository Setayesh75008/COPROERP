from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class PreparationRelances(models.TransientModel):
    """Suivi des impayés et préparation des relances d'une copropriété."""

    _name = "coproerp.relance.preparation"
    _description = "Préparation des relances"

    copropriete_id = fields.Many2one("coproerp.copropriete", string="Copropriété", required=True)
    date = fields.Date(string="Situation au", required=True, default=fields.Date.context_today)
    ligne_ids = fields.One2many("coproerp.relance.preparation.ligne", "preparation_id", string="Débiteurs")
    recherche_faite = fields.Boolean()

    @api.model
    def default_get(self, champs):
        valeurs = super().default_get(champs)
        if self.env.context.get("active_model") == "coproerp.copropriete" and self.env.context.get("active_id"):
            valeurs.setdefault("copropriete_id", self.env.context["active_id"])
        return valeurs

    def _proposition(self, personne, situation):
        copro = self.copropriete_id
        Relance = self.env["coproerp.relance"]
        commun = [("copropriete_id", "=", copro.id), ("personne_id", "=", personne.id)]
        if Relance.search_count(commun + [("etat", "=", "brouillon")]):
            return "aucune", "Une lettre est déjà préparée (brouillon)."
        if situation["jours_retard"] < copro.recouvrement_jours_avant_relance:
            return "aucune", "Retard de %d jour(s) : relance à partir de %d jours." % (
                situation["jours_retard"], copro.recouvrement_jours_avant_relance)
        derniere = Relance.search(commun + [
            ("etat", "=", "envoyee"), ("date", ">=", situation["plus_ancienne"]),
        ], order="date desc, id desc", limit=1)
        if not derniere:
            return "relance", "Aucune relance depuis l'échéance impayée du %s." % (
                situation["plus_ancienne"].strftime("%d/%m/%Y"))
        if derniere.type_relance == "mise_en_demeure":
            if derniere.date_limite and self.date > derniere.date_limite:
                return "aucune", ("Mise en demeure %s restée sans effet (délai expiré le %s) : "
                                  "art. 19-2 applicable, dossier à transmettre à l'avocat ou au "
                                  "commissaire de justice." % (derniere.name, derniere.date_limite.strftime("%d/%m/%Y")))
            return "aucune", "Mise en demeure %s en cours (fin du délai le %s)." % (
                derniere.name, derniere.date_limite.strftime("%d/%m/%Y") if derniere.date_limite else "?")
        possible = derniere.date + timedelta(days=copro.recouvrement_jours_avant_mise_en_demeure)
        if self.date >= possible:
            return "mise_en_demeure", "Relance %s du %s restée sans effet." % (
                derniere.name, derniere.date.strftime("%d/%m/%Y"))
        return "aucune", "Relance %s du %s : mise en demeure possible à partir du %s." % (
            derniere.name, derniere.date.strftime("%d/%m/%Y"), possible.strftime("%d/%m/%Y"))

    def action_rechercher(self):
        self.ensure_one()
        copro = self.copropriete_id
        copro._verifier_dossier()
        commandes = [Command.clear()]
        for personne in copro.debiteurs(self.date).sorted("name"):
            situation = copro.situation_debiteur(personne, self.date)
            if situation["solde"] < (copro.recouvrement_seuil or 0.0):
                continue
            proposition, motif = self._proposition(personne, situation)
            commandes.append(Command.create({
                "personne_id": personne.id,
                "solde": situation["solde"],
                "plus_ancienne": situation["plus_ancienne"],
                "jours_retard": situation["jours_retard"],
                "proposition": proposition,
                "motif": motif,
                "a_traiter": proposition != "aucune",
            }))
        self.write({"ligne_ids": commandes, "recherche_faite": True})
        return self._rouvrir()

    def _rouvrir(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Suivi des impayés et relances",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_preparer(self):
        self.ensure_one()
        lignes = self.ligne_ids.filtered(lambda l: l.a_traiter and l.proposition != "aucune")
        if not lignes:
            raise UserError("Aucune lettre à préparer : cochez au moins un débiteur avec une proposition.")
        relances = self.env["coproerp.relance"].create([{
            "copropriete_id": self.copropriete_id.id,
            "personne_id": ligne.personne_id.id,
            "type_relance": ligne.proposition,
            "date": self.date,
        } for ligne in lignes])
        return {
            "type": "ir.actions.act_window",
            "name": "Lettres préparées",
            "res_model": "coproerp.relance",
            "view_mode": "list,form",
            "domain": [("id", "in", relances.ids)],
        }


class PreparationRelancesLigne(models.TransientModel):
    _name = "coproerp.relance.preparation.ligne"
    _description = "Débiteur à relancer"
    _order = "jours_retard desc, solde desc"

    preparation_id = fields.Many2one("coproerp.relance.preparation", required=True, ondelete="cascade")
    personne_id = fields.Many2one("res.partner", string="Copropriétaire", readonly=True)
    solde = fields.Float(string="Solde dû", digits=(16, 2), readonly=True)
    plus_ancienne = fields.Date(string="Impayé depuis", readonly=True)
    jours_retard = fields.Integer(string="Jours de retard", readonly=True)
    proposition = fields.Selection(
        [("relance", "Lettre de relance"), ("mise_en_demeure", "Mise en demeure"), ("aucune", "Rien pour l'instant")],
        string="Proposition",
    )
    motif = fields.Char(string="Situation", readonly=True)
    a_traiter = fields.Boolean(string="Préparer")
