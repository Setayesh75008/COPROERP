from odoo import fields, models


class RibDemande(models.Model):
    _name = "coproerp.rib.demande"
    _description = "Demande de prélèvement SEPA (dépôt de RIB)"
    _inherit = ["mail.thread"]
    _order = "create_date desc"
    _rec_name = "personne_id"

    personne_id = fields.Many2one(
        "res.partner",
        string="Copropriétaire",
        required=True,
        ondelete="cascade",
        index=True,
    )
    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
    )
    fichier = fields.Binary(string="RIB", attachment=True, required=True)
    nom_fichier = fields.Char(string="Nom du fichier")
    etat = fields.Selection(
        [
            ("nouveau", "Reçu"),
            ("mandat_envoye", "Mandat SEPA envoyé"),
            ("actif", "Prélèvement en place"),
            ("refuse", "Refusé / incomplet"),
        ],
        string="État",
        default="nouveau",
        required=True,
        tracking=True,
    )
    note = fields.Text(string="Observations")
