from odoo import api, fields, models

# Types de droit ouvrant l'accès à l'extranet.
# Les locataires ("locataire") n'y ont pas accès.
TYPES_DROIT_EXTRANET = (
    "proprietaire",
    "usufruitier",
    "nu_proprietaire",
    "indivisaire",
)


class Droit(models.Model):
    _inherit = "coproerp.droit"

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        related="lot_id.copropriete_id",
        store=True,
        readonly=True,
        index=True,
    )

    # Champ stocké (et non calculé à la volée) pour pouvoir être utilisé
    # dans les règles d'accès : il est mis à jour à chaque création /
    # modification et chaque nuit (dates de début et de fin).
    acces_extranet = fields.Boolean(
        string="Accès extranet",
        readonly=True,
        copy=False,
        index=True,
        help="Coché automatiquement lorsque le droit est en cours et que son "
        "type (propriétaire, usufruitier, nu-propriétaire, indivisaire) "
        "ouvre l'accès à l'extranet.",
    )

    def _calcul_acces_extranet(self, today=None):
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        return bool(
            self.active
            and self.type_droit in TYPES_DROIT_EXTRANET
            and (not self.date_debut or self.date_debut <= today)
            and (not self.date_fin or self.date_fin >= today)
        )

    def _maj_acces_extranet(self):
        today = fields.Date.context_today(self)
        for droit in self.with_context(active_test=False):
            valeur = droit._calcul_acces_extranet(today)
            if droit.acces_extranet != valeur:
                super(Droit, droit).write({"acces_extranet": valeur})

    @api.model_create_multi
    def create(self, vals_list):
        droits = super().create(vals_list)
        droits._maj_acces_extranet()
        return droits

    def write(self, vals):
        res = super().write(vals)
        if {"active", "type_droit", "date_debut", "date_fin"} & set(vals):
            self._maj_acces_extranet()
        return res

    @api.model
    def _cron_maj_acces_extranet(self):
        self.with_context(active_test=False).search([])._maj_acces_extranet()
