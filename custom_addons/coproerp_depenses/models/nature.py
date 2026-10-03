from odoo import api, fields, models


class NatureDepense(models.Model):
    _name = "coproerp.nature.depense"
    _description = "Nature de dépense (compte de charges)"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char(
        string="Compte",
        required=True,
        help="Numéro du compte de charges à 6 chiffres (ex. : 615000).",
    )
    name = fields.Char(string="Libellé", required=True)
    travaux = fields.Boolean(
        string="Travaux hors budget",
        help="Travaux décidés par l'assemblée générale (art. 14-2 de la loi de 1965) : "
        "la facture doit être rattachée à une opération de travaux et n'est pas "
        "imputée sur le budget prévisionnel.",
    )
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "Une nature de dépense existe déjà pour ce compte.",
    )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for nature in self:
            nature.display_name = "%s – %s" % (nature.code or "", nature.name or "")
