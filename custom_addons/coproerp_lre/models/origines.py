from odoo import fields, models
from odoo.exceptions import UserError

ETATS_TRANSMIS = ("a_valider", "envoye", "recu", "refuse", "negligence")


def _pdf(env, xmlid, records):
    rapport = env.ref(xmlid)
    pdf, _format = env["ir.actions.report"].with_context(discard_logo_check=True)._render_qweb_pdf(
        rapport.report_name, records.ids)
    return pdf


def _notification(titre, lignes, type_message="success"):
    return {
        "type": "ir.actions.client", "tag": "display_notification",
        "params": {"title": titre, "message": "\n".join(lignes), "type": type_message, "sticky": True},
    }


def _envoyer(envois):
    """Expédie les envois et résume le résultat."""
    envois.action_envoyer()
    transmis = envois.filtered(lambda e: e.etat in ETATS_TRANSMIS)
    a_valider = transmis.filtered(lambda e: e.etat == "a_valider")
    echecs = envois - transmis
    lignes = ["%d lettre(s) transmise(s) à AR24." % len(transmis)]
    if a_valider:
        lignes.append("%d à valider depuis votre espace AR24 (liste d'attente) dans les 7 jours." % len(a_valider))
    for envoi in echecs:
        lignes.append("Échec pour %s : %s" % (envoi.personne_id.name, envoi.erreur or ""))
    return _notification("Lettres recommandées électroniques", lignes, "warning" if echecs else "success")


class Relance(models.Model):
    _inherit = "coproerp.relance"

    lre_envoi_id = fields.Many2one("coproerp.lre.envoi", string="Lettre recommandée électronique", readonly=True,
                                   copy=False)
    lre_etat = fields.Selection(related="lre_envoi_id.etat", string="Suivi AR24")

    def action_envoyer_lre(self):
        Envoi = self.env["coproerp.lre.envoi"]
        envois = Envoi
        for relance in self:
            if relance.etat != "envoyee" or relance.mode_envoi != "lre":
                raise UserError("Seule une lettre validée, à notifier par lettre recommandée électronique, peut être "
                                "transmise à AR24.")
            if relance.lre_envoi_id and relance.lre_envoi_id.etat in ETATS_TRANSMIS:
                raise UserError("Cette lettre a déjà été transmise à AR24.")
            envoi = relance.lre_envoi_id
            if not envoi:
                objet = "%s %s" % ("Mise en demeure" if relance.type_relance == "mise_en_demeure" else "Relance",
                                   relance.name)
                envoi = Envoi.preparer(relance, relance.copropriete_id, relance.personne_id, relance.adresse_email,
                                       objet, _pdf(self.env, "coproerp_recouvrement.action_report_relance", relance),
                                       "%s.pdf" % relance.name.replace("/", "-"))
                relance.lre_envoi_id = envoi
            envois |= envoi
        return _envoyer(envois)

    def _lre_mise_a_jour(self, envoi):
        vals = {}
        if envoi.ar24_id and not self.numero_envoi:
            vals["numero_envoi"] = "AR24 n° %s" % envoi.ar24_id
        if envoi.date_depot and not self.date_presentation:
            vals["date_presentation"] = envoi.date_locale(envoi.date_depot)
        if vals:
            self.write(vals)


class Convocation(models.Model):
    _inherit = "coproerp.ag.convocation"

    lre_envoi_id = fields.Many2one("coproerp.lre.envoi", string="Lettre recommandée électronique", readonly=True,
                                   copy=False)
    lre_etat = fields.Selection(related="lre_envoi_id.etat", string="Suivi AR24")

    def _lre_mise_a_jour(self, envoi):
        vals = {}
        if envoi.etat in ETATS_TRANSMIS and self.etat == "a_envoyer":
            vals.update(etat="envoyee", date_envoi=self.date_envoi or fields.Date.context_today(self))
        if envoi.ar24_id and not self.numero_envoi:
            vals["numero_envoi"] = "AR24 n° %s" % envoi.ar24_id
        if envoi.date_depot and not self.date_presentation:
            vals["date_presentation"] = envoi.date_locale(envoi.date_depot)
        if vals:
            self.write(vals)


class Presence(models.Model):
    _inherit = "coproerp.ag.presence"

    lre_envoi_id = fields.Many2one("coproerp.lre.envoi", string="Lettre recommandée électronique (PV)",
                                   readonly=True, copy=False)
    lre_etat = fields.Selection(related="lre_envoi_id.etat", string="Suivi AR24")

    def _lre_mise_a_jour(self, envoi):
        vals = {}
        if envoi.ar24_id and not self.pv_numero_envoi:
            vals["pv_numero_envoi"] = "AR24 n° %s" % envoi.ar24_id
        if envoi.date_depot and not self.pv_date_presentation:
            vals["pv_date_presentation"] = envoi.date_locale(envoi.date_depot)
        if vals:
            self.write(vals)


class AssembleeGenerale(models.Model):
    _inherit = "coproerp.ag"

    lre_nombre = fields.Integer(string="Lettres AR24", compute="_compute_lre_nombre")

    def _lre_envois(self):
        self.ensure_one()
        return (self.convocation_ids.lre_envoi_id | self.presence_ids.lre_envoi_id)

    def _compute_lre_nombre(self):
        for ag in self:
            ag.lre_nombre = len(ag._lre_envois())

    def action_envoyer_convocations_lre(self):
        self.ensure_one()
        convocations = self.convocation_ids.filtered(
            lambda c: c.etat == "a_envoyer" and c.mode_envoi == "lre"
            and not (c.lre_envoi_id and c.lre_envoi_id.etat in ETATS_TRANSMIS))
        if not convocations:
            raise UserError("Aucune convocation à notifier par lettre recommandée électronique.")
        sans_adresse = convocations.filtered(lambda c: not (c.adresse_email or "").strip())
        if sans_adresse:
            raise UserError("Adresse électronique manquante pour : %s." % ", ".join(sans_adresse.personne_id.mapped("name")))
        Envoi = self.env["coproerp.lre.envoi"]
        envois = Envoi
        for convocation in convocations:
            envoi = convocation.lre_envoi_id
            if not envoi:
                envoi = Envoi.preparer(
                    convocation, self.copropriete_id, convocation.personne_id, convocation.adresse_email,
                    "Convocation à l'assemblée générale du %s" % self.date_ag.strftime("%d/%m/%Y"),
                    _pdf(self.env, "coproerp_ag.action_report_dossier_convocation", convocation),
                    "Convocation AG %s - %s.pdf" % (self.date_ag.strftime("%Y-%m-%d"), convocation.personne_id.name))
                convocation.lre_envoi_id = envoi
            envois |= envoi
        return _envoyer(envois)

    def action_notifier_pv_lre(self):
        self.ensure_one()
        Mode = self.env["coproerp.notification.mode"]
        Envoi = self.env["coproerp.lre.envoi"]
        lignes = self.presence_ids.filtered(
            lambda p: p.pv_a_notifier and not (p.lre_envoi_id and p.lre_envoi_id.etat in ETATS_TRANSMIS))
        envois = Envoi
        for ligne in lignes:
            mode, adresse = Mode.mode_au(ligne.personne_id, fields.Date.context_today(self))
            if not ligne.pv_mode_envoi:
                ligne.pv_mode_envoi = "lre" if mode == "electronique" else "lrar"
            if ligne.pv_mode_envoi != "lre":
                continue
            if not adresse:
                raise UserError("%s n'a pas d'adresse électronique de notification : notifiez le procès-verbal par "
                                "lettre recommandée postale." % ligne.personne_id.name)
            envoi = ligne.lre_envoi_id
            if not envoi:
                envoi = Envoi.preparer(
                    ligne, self.copropriete_id, ligne.personne_id, adresse,
                    "Notification du procès-verbal de l'assemblée générale du %s" % self.date_ag.strftime("%d/%m/%Y"),
                    _pdf(self.env, "coproerp_ag.action_report_pv_notification", ligne),
                    "PV AG %s - %s.pdf" % (self.date_ag.strftime("%Y-%m-%d"), ligne.personne_id.name))
                ligne.lre_envoi_id = envoi
            envois |= envoi
        if not envois:
            raise UserError("Aucun opposant ou défaillant à notifier par lettre recommandée électronique.")
        return _envoyer(envois)

    def action_voir_lre(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Lettres recommandées électroniques",
            "res_model": "coproerp.lre.envoi", "view_mode": "list,form",
            "domain": [("id", "in", self._lre_envois().ids)],
        }
