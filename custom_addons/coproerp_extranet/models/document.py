from markupsafe import escape

from odoo import api, fields, models
from odoo.exceptions import ValidationError

VISIBILITES = [
    ("tous", "Tous les copropriétaires"),
    ("conseil_syndical", "Conseil syndical uniquement"),
    ("personnel", "Un copropriétaire (document personnel)"),
]


class DocumentCategorie(models.Model):
    _name = "coproerp.extranet.document.categorie"
    _description = "Catégorie de document extranet"
    _order = "sequence, name"

    name = fields.Char(string="Catégorie", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    visibilite_defaut = fields.Selection(
        VISIBILITES,
        string="Visibilité par défaut",
        required=True,
        default="tous",
    )
    obligatoire = fields.Boolean(
        string="Document réglementaire",
        help="Fait partie de la liste minimale du décret n° 2019-502 du 23 mai 2019.",
    )
    reference_legale = fields.Char(string="Référence")
    description = fields.Text(string="Description")


class ExtranetDocument(models.Model):
    _name = "coproerp.extranet.document"
    _description = "Document de l'extranet"
    _inherit = ["mail.thread"]
    _order = "date_document desc, id desc"

    name = fields.Char(string="Titre", required=True, tracking=True)

    copropriete_id = fields.Many2one(
        "coproerp.copropriete",
        string="Copropriété",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    categorie_id = fields.Many2one(
        "coproerp.extranet.document.categorie",
        string="Catégorie",
        required=True,
        ondelete="restrict",
        tracking=True,
    )

    visibilite = fields.Selection(
        VISIBILITES,
        string="Visible par",
        required=True,
        default="tous",
        tracking=True,
    )

    personne_id = fields.Many2one(
        "res.partner",
        string="Copropriétaire destinataire",
        index=True,
        tracking=True,
        help="Obligatoire pour un document personnel.",
    )

    appel_id = fields.Many2one(
        "coproerp.appel.charge",
        string="Appel de fonds lié",
        ondelete="set null",
    )

    fichier = fields.Binary(string="Fichier", attachment=True, required=True)
    nom_fichier = fields.Char(string="Nom du fichier")

    date_document = fields.Date(
        string="Date du document",
        default=fields.Date.context_today,
        required=True,
    )

    publie = fields.Boolean(
        string="Publié",
        default=False,
        tracking=True,
        help="Un document n'est visible sur l'extranet qu'une fois publié.",
    )
    date_publication = fields.Datetime(string="Publié le", readonly=True)

    description = fields.Text(string="Description")

    lecture_ids = fields.One2many(
        "coproerp.extranet.document.lecture",
        "document_id",
        string="Consultations",
        readonly=True,
    )
    lecture_count = fields.Integer(
        string="Nombre de consultations",
        compute="_compute_lecture_count",
    )

    @api.depends("lecture_ids")
    def _compute_lecture_count(self):
        for doc in self:
            doc.lecture_count = len(doc.lecture_ids)

    @api.onchange("categorie_id")
    def _onchange_categorie_id(self):
        if self.categorie_id:
            self.visibilite = self.categorie_id.visibilite_defaut

    @api.constrains("visibilite", "personne_id")
    def _check_personne(self):
        for doc in self:
            if doc.visibilite == "personnel" and not doc.personne_id:
                raise ValidationError(
                    "Un document personnel doit avoir un copropriétaire destinataire."
                )

    # ---------------------------------------------------------------
    # Publication et notification
    # ---------------------------------------------------------------
    def action_publier(self):
        for doc in self.filtered(lambda d: not d.publie):
            doc.write({"publie": True, "date_publication": fields.Datetime.now()})
            doc._notifier_publication()

    def action_depublier(self):
        self.write({"publie": False})

    def _destinataires(self):
        """Personnes (res.partner) pouvant voir ce document sur l'extranet."""
        self.ensure_one()
        Partner = self.env["res.partner"]
        if self.visibilite == "personnel":
            return self.personne_id
        if self.visibilite == "conseil_syndical":
            return self.copropriete_id.mandat_cs_ids.filtered("en_cours").personne_id
        droits = self.copropriete_id.droit_ids.filtered("acces_extranet")
        membres_cs = self.copropriete_id.mandat_cs_ids.filtered("en_cours")
        return (droits.personne_id | membres_cs.personne_id) or Partner

    def _notifier_publication(self):
        """E-mail aux destinataires ayant activé l'alerte « nouveaux documents »."""
        self.ensure_one()
        base_url = self.get_base_url()
        destinataires = self._destinataires().filtered(
            lambda p: p.email and p.extranet_notif_documents
        )
        Mail = self.env["mail.mail"].sudo()
        for partner in destinataires:
            corps = (
                "<p>Bonjour %s,</p>"
                "<p>Un nouveau document est disponible sur votre extranet "
                "pour la copropriété <b>%s</b> :</p>"
                "<p><b>%s</b> (%s)</p>"
                '<p><a href="%s/extranet/documents">Consulter mes documents</a></p>'
                "<p>Vous pouvez désactiver ces alertes dans « Mon compte ».</p>"
            ) % (
                escape(partner.name or ""),
                escape(self.copropriete_id.name or ""),
                escape(self.name or ""),
                escape(self.categorie_id.name or ""),
                base_url,
            )
            Mail.create(
                {
                    "subject": "Nouveau document : %s" % self.name,
                    "email_to": partner.email_formatted,
                    "body_html": corps,
                    "auto_delete": True,
                }
            )

    # ---------------------------------------------------------------
    # Lecture
    # ---------------------------------------------------------------
    def _marquer_lu(self, partner):
        """Enregistre la première consultation du document par ``partner``."""
        Lecture = self.env["coproerp.extranet.document.lecture"].sudo()
        for doc in self:
            deja = Lecture.search_count(
                [("document_id", "=", doc.id), ("personne_id", "=", partner.id)]
            )
            if not deja:
                Lecture.create({"document_id": doc.id, "personne_id": partner.id})


class ExtranetDocumentLecture(models.Model):
    _name = "coproerp.extranet.document.lecture"
    _description = "Consultation d'un document de l'extranet"
    _order = "date_lecture desc"

    document_id = fields.Many2one(
        "coproerp.extranet.document",
        string="Document",
        required=True,
        ondelete="cascade",
        index=True,
    )
    personne_id = fields.Many2one(
        "res.partner",
        string="Consulté par",
        required=True,
        ondelete="cascade",
        index=True,
    )
    date_lecture = fields.Datetime(
        string="Première consultation",
        default=fields.Datetime.now,
        required=True,
    )

    _document_personne_uniq = models.Constraint(
        "UNIQUE(document_id, personne_id)",
        "Une seule consultation est enregistrée par personne et par document.",
    )
