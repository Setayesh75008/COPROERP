from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round


class TravauxFinancement(models.Model):
    _inherit = "coproerp.travaux.financement"

    honoraires_syndic = fields.Float(
        string="Honoraires du syndic sur travaux (TTC)",
        digits=(16, 2),
        help="Honoraires votés en assemblée générale (art. 18-1 A de la loi du "
        "10 juillet 1965). Ils sont appelés au même rythme que les travaux, "
        "sur une ligne distincte de l'avis.",
    )
    echeance_ids = fields.One2many(
        "coproerp.travaux.echeance", "financement_id", string="Échéancier des appels"
    )
    total_pourcentage = fields.Float(
        string="Total de l'échéancier (%)", compute="_compute_total_pourcentage"
    )

    @api.depends("echeance_ids.pourcentage")
    def _compute_total_pourcentage(self):
        for financement in self:
            financement.total_pourcentage = sum(financement.echeance_ids.mapped("pourcentage"))

    @api.constrains("honoraires_syndic")
    def _check_honoraires(self):
        for financement in self:
            if financement.honoraires_syndic < 0:
                raise ValidationError("Les honoraires ne peuvent pas être négatifs.")

    def action_generer_echeancier_egal(self):
        """Crée un échéancier en parts égales, sur la base du nombre d'appels."""
        for financement in self:
            if financement.echeance_ids.filtered("appel_ids"):
                raise UserError("Des appels ont déjà été générés : modifiez l'échéancier à la main.")
            financement.echeance_ids.unlink()
            nombre = financement.nombre_appels or 1
            base = float_round(100.0 / nombre, precision_digits=2)
            depart = financement.date_prevue or fields.Date.context_today(self)
            for rang in range(1, nombre + 1):
                pct = base if rang < nombre else float_round(100.0 - base * (nombre - 1), precision_digits=2)
                self.env["coproerp.travaux.echeance"].create({
                    "financement_id": financement.id,
                    "sequence": rang * 10,
                    "pourcentage": pct,
                    "date_echeance": depart,
                })

    # Les montants des appels issus d'un échéancier ne doivent pas être
    # recalculés par la règle d'origine (montant_par_appel identique pour
    # tous les appels) : voir AppelChargePoste._get_financement_exceptionnel.


class TravauxEcheance(models.Model):
    _name = "coproerp.travaux.echeance"
    _description = "Échéance d'appel de fonds travaux"
    _order = "financement_id, sequence, date_echeance, id"

    financement_id = fields.Many2one(
        "coproerp.travaux.financement", required=True, ondelete="cascade", index=True
    )
    travaux_id = fields.Many2one(related="financement_id.travaux_id", store=True)
    copropriete_id = fields.Many2one(related="financement_id.copropriete_id", store=True)
    sequence = fields.Integer(default=10)
    numero = fields.Integer(string="N° d'appel", compute="_compute_numero", store=True)
    name = fields.Char(
        string="Libellé",
        help="Libellé sur l'avis. Par défaut : « APPEL 40 % <travaux> ».",
    )
    pourcentage = fields.Float(string="% des travaux", digits=(16, 2), required=True)
    date_echeance = fields.Date(string="Échéance", required=True)
    date_edition = fields.Date(
        string="Date d'édition",
        help="Date figurant sur l'avis. Par défaut : 15 jours avant l'échéance.",
    )
    montant = fields.Float(
        string="Montant travaux", compute="_compute_montants", digits=(16, 2), store=True
    )
    montant_honoraires = fields.Float(
        string="Honoraires", compute="_compute_montants", digits=(16, 2), store=True
    )
    appel_ids = fields.One2many("coproerp.appel.charge", "echeance_travaux_id", string="Appels")
    appel_count = fields.Integer(compute="_compute_appel_count")

    @api.depends("sequence", "financement_id.echeance_ids.sequence")
    def _compute_numero(self):
        for echeance in self:
            ordre = echeance.financement_id.echeance_ids.sorted(
                lambda e: (e.sequence, e.date_echeance or fields.Date.today(), e.id)
            )
            echeance.numero = (ordre.ids.index(echeance.id) + 1) if echeance.id in ordre.ids else 0

    @api.depends("pourcentage", "financement_id.montant_prevu", "financement_id.honoraires_syndic")
    def _compute_montants(self):
        for echeance in self:
            f = echeance.financement_id
            echeance.montant = float_round(f.montant_prevu * echeance.pourcentage / 100.0, precision_digits=2)
            echeance.montant_honoraires = float_round(
                f.honoraires_syndic * echeance.pourcentage / 100.0, precision_digits=2
            )

    def _compute_appel_count(self):
        for echeance in self:
            echeance.appel_count = len(echeance.appel_ids)

    @api.constrains("pourcentage")
    def _check_pourcentage(self):
        for echeance in self:
            if echeance.pourcentage <= 0 or echeance.pourcentage > 100:
                raise ValidationError("Le pourcentage d'une échéance doit être compris entre 0 et 100.")

    def _libelle(self):
        self.ensure_one()
        if self.name:
            return self.name
        return ("APPEL %s %% %s" % (
            ("%g" % self.pourcentage).replace(".", ","),
            self.travaux_id.name or "",
        )).upper()

    def action_generer_appels(self):
        """Génère les appels de fonds de cette échéance."""
        Appel = self.env["coproerp.appel.charge"]
        crees, messages = Appel.browse(), []
        for echeance in self:
            f = echeance.financement_id
            travaux = f.travaux_id
            if f.type_financement != "appel_exceptionnel":
                raise UserError("Seuls les financements par appel exceptionnel génèrent des appels.")
            if not f.repartition_id:
                raise UserError("Indiquez la clé de répartition du financement « %s »." % f.name)
            if float_compare(f.total_pourcentage, 100.0, precision_digits=2) > 0:
                raise UserError("L'échéancier dépasse 100 %% (%.2f %%)." % f.total_pourcentage)
            if travaux.etat in ("projet", "annule"):
                raise UserError("Les travaux doivent être votés avant d'appeler des fonds.")
            lignes = [{
                "type_poste": "travaux_exceptionnels",
                "designation": echeance._libelle(),
                "repartition": f.repartition_id,
                "montant": echeance.montant,
            }]
            if echeance.montant_honoraires:
                lignes.append({
                    "type_poste": "travaux_exceptionnels",
                    "designation": "HONORAIRES SYNDIC",
                    "repartition": f.repartition_id,
                    "montant": echeance.montant_honoraires,
                })
            date_edition = echeance.date_edition or (echeance.date_echeance - timedelta(days=15))
            appels, msg = Appel._generer_appels(
                travaux.copropriete_id,
                lignes,
                {
                    "type_appel": "appel_exceptionnel",
                    "travaux_id": travaux.id,
                    "echeance_travaux_id": echeance.id,
                    "numero_appel_travaux": echeance.numero,
                    "date_appel": min(date_edition, echeance.date_echeance),
                    "date_echeance": echeance.date_echeance,
                    "note": "Travaux %s — %s." % (travaux.reference, echeance._libelle()),
                },
                [("echeance_travaux_id", "=", echeance.id)],
                date_ref=echeance.date_echeance,
            )
            crees |= appels
            messages += msg
        return Appel._action_resultat(crees, "Appels de travaux", messages)

    def action_voir_appels(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Appels de l'échéance",
            "res_model": "coproerp.appel.charge",
            "view_mode": "list,form",
            "domain": [("echeance_travaux_id", "=", self.id)],
        }
