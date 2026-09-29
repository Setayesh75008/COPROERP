from odoo import fields, models
from odoo.exceptions import UserError

# Droits dont le titulaire doit recevoir les appels de fonds.
TYPES_DROIT_APPELS = (
    "proprietaire",
    "indivisaire",
    "usufruitier",
    "nu_proprietaire",
)


class Lot(models.Model):
    _inherit = "coproerp.lot"

    escalier = fields.Char(string="Escalier")

    propriete_syndicat = fields.Boolean(
        string="Lot appartenant au syndicat",
        help="Le syndicat ne s'appelle pas de fonds à lui-même : ce lot est "
        "exclu de la génération des appels. Pensez à le retirer aussi des "
        "clés de répartition, sinon la part correspondante n'est appelée à "
        "personne.",
    )

    mandataire_commun_id = fields.Many2one(
        "res.partner",
        string="Mandataire commun",
        help="En cas d'indivision ou de démembrement de propriété "
        "(usufruit / nue-propriété), les intéressés sont représentés par un "
        "mandataire commun (art. 23 de la loi du 10 juillet 1965). "
        "Les appels de fonds de ce lot lui sont adressés.",
    )

    droit_ids = fields.One2many(
        "coproerp.droit",
        "lot_id",
        string="Droits sur le lot",
    )

    def _titulaires_appels(self, date_ref=None):
        """Titulaires de droits en cours ouvrant l'obligation aux charges."""
        self.ensure_one()
        date_ref = date_ref or fields.Date.context_today(self)
        droits = self.droit_ids.filtered(
            lambda d: d.active
            and d.type_droit in TYPES_DROIT_APPELS
            and (not d.date_debut or d.date_debut <= date_ref)
            and (not d.date_fin or d.date_fin >= date_ref)
        )
        return droits.personne_id

    def _destinataire_appels(self, date_ref=None):
        """Personne à qui adresser les appels de fonds de ce lot.

        - lot du syndicat : aucun destinataire (lot exclu) ;
        - mandataire commun renseigné : le mandataire ;
        - un seul titulaire (fiches Droit) : ce titulaire ;
        - aucune fiche Droit : le propriétaire unique indiqué sur le lot
          (compatibilité avec les données saisies avant les fiches Droit) ;
        - plusieurs titulaires sans mandataire commun : erreur explicite.

        Retourne (partner, message_erreur).
        """
        self.ensure_one()
        Partner = self.env["res.partner"]
        if self.propriete_syndicat:
            return Partner, False
        if self.mandataire_commun_id:
            return self.mandataire_commun_id, False
        titulaires = self._titulaires_appels(date_ref)
        if len(titulaires) == 1:
            return titulaires, False
        if not titulaires:
            if len(self.proprietaire_ids) == 1:
                return self.proprietaire_ids, False
            if not self.proprietaire_ids:
                return Partner, "Lot %s : aucun propriétaire (fiche Droit) en cours." % self.numero
            return Partner, (
                "Lot %s : plusieurs propriétaires sans mandataire commun." % self.numero
            )
        return Partner, (
            "Lot %s : %s titulaires (%s) — indiquez le mandataire commun "
            "(art. 23 loi 1965) sur la fiche du lot."
            % (self.numero, len(titulaires), ", ".join(titulaires.mapped("name")))
        )

    def action_verifier_destinataires(self):
        """Contrôle, sans rien générer, que chaque lot a un destinataire."""
        erreurs = []
        for lot in self:
            _partner, erreur = lot._destinataire_appels()
            if erreur:
                erreurs.append(erreur)
        if erreurs:
            raise UserError("\n".join(erreurs))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Destinataires des appels",
                "message": "Chaque lot a un destinataire identifié.",
                "type": "success",
            },
        }
