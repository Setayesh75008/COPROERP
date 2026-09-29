from odoo import models, fields, _


class Copropriete(models.Model):
    _name = "coproerp.copropriete"
    _description = "Copropriété"
    _rec_name = "name"
    _order = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(
        string="Nom",
        required=True,
    )

    reference = fields.Char(
        string="Référence",
        readonly=True,
        copy=False,
    )

    street = fields.Char(string="Adresse")
    zip = fields.Char(string="Code postal")
    city = fields.Char(string="Ville")

    country_id = fields.Many2one(
        "res.country",
        string="Pays",
    )

    siren = fields.Char(string="SIREN")

    siret = fields.Char(
        string="SIRET"
    )

    numero_rnc = fields.Char(
        string="Numéro RNC"
    )

    date_immatriculation = fields.Date(
        string="Date immatriculation RNC"
    )

    date_creation = fields.Date(
        string="Date de création"
    )

    date_debut_contrat = fields.Date(
        string="Début du contrat"
    )

    date_fin_contrat = fields.Date(
        string="Fin du contrat"
    )
    annee_construction = fields.Integer(
        string="Année de construction"
    )

    nombre_entrees = fields.Integer(
        string="Nombre d'entrées",
        default=1,
    )

    nombre_ascenseurs = fields.Integer(
        string="Nombre d'ascenseurs",
        default=0,
    )

    nombre_gardiens = fields.Integer(
        string="Nombre de gardiens",
        default=0,
    )
    
    syndic_id = fields.Many2one(
        "res.partner",
        string="Syndic",
        domain="[('is_company', '=', True)]",
    )   

    date_reglement = fields.Date(
        string="Date règlement de copropriété"
    )

    date_derniere_ag = fields.Date(
        string="Date dernière AG"
    )

    date_prochaine_ag = fields.Date(
    string="Date prochaine AG"
)

    nombre_batiments = fields.Integer(
        string="Nombre de bâtiments",
        default=1,
    )

    nombre_lots = fields.Integer(
        string="Nombre de lots",
        default=0,
    )

    nombre_lots_principaux = fields.Integer(
        string="Lots principaux",
        default=0,
    )

    nombre_lots_secondaires = fields.Integer(
        string="Lots secondaires",
        default=0,
    )

    note = fields.Text(
        string="Observations"
    )

    
    image_1920 = fields.Image(
        string="Photo",
        max_width=1920,
        max_height=1920,
    )

    def action_view_batiments(self):
        self.ensure_one()

        return {
            "name": _("Bâtiments"),
            "type": "ir.actions.act_window",
            "res_model": "coproerp.batiment",
            "view_mode": "list,form",
            "domain": [("copropriete_id", "=", self.id)],
            "context": {
                "default_copropriete_id": self.id,
            },
        }
