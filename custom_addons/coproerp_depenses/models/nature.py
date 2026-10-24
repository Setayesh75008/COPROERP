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
    recuperable = fields.Selection(
        [("oui", "Récupérable"), ("non", "Non récupérable"), ("partiel", "Partiellement récupérable")],
        string="Récupérable sur le locataire",
        help="Charges que le copropriétaire bailleur peut récupérer sur son locataire (décret n° 87-713 du "
             "26 août 1987). Valeur indicative, à adapter : un même compte peut regrouper des dépenses "
             "récupérables et non récupérables.",
    )
    taux_recuperable = fields.Float(
        string="Part récupérable (%)", digits=(5, 2),
        help="Pour une charge partiellement récupérable (ex. : rémunération du gardien, 75 % ou 40 %).",
    )

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "Une nature de dépense existe déjà pour ce compte.",
    )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for nature in self:
            nature.display_name = "%s – %s" % (nature.code or "", nature.name or "")

    # Valeurs par défaut (décret n° 87-713) : code -> (récupérabilité, taux)
    RECUPERABILITE = {
        "601000": ("oui", 100), "602000": ("oui", 100), "603000": ("oui", 100), "604000": ("oui", 100),
        "605000": ("non", 0), "606000": ("oui", 100), "611000": ("oui", 100), "612000": ("non", 0),
        "613000": ("non", 0), "614000": ("oui", 100), "615000": ("oui", 100), "616000": ("non", 0),
        "621000": ("non", 0), "622000": ("non", 0), "623000": ("non", 0), "624000": ("non", 0),
        "632000": ("oui", 100), "633000": ("non", 0), "634000": ("non", 0),
        "641000": ("partiel", 75), "642000": ("partiel", 75), "643000": ("partiel", 75), "644000": ("non", 0),
        "661000": ("non", 0), "662000": ("non", 0), "671000": ("non", 0), "672000": ("non", 0),
        "673000": ("non", 0), "678000": ("non", 0),
    }

    @api.model
    def _initialiser_recuperabilite(self):
        """Renseigne la récupérabilité des natures qui n'en ont pas encore (installation ou mise à jour)."""
        for nature in self.with_context(active_test=False).search([("recuperable", "=", False)]):
            valeur = self.RECUPERABILITE.get(nature.code)
            if valeur:
                nature.write({"recuperable": valeur[0], "taux_recuperable": valeur[1]})

    def libelle_recuperable(self):
        self.ensure_one()
        if self.recuperable == "oui":
            return "R"
        if self.recuperable == "partiel":
            return "R %s %%" % ("%g" % self.taux_recuperable)
        if self.recuperable == "non":
            return "NR"
        return ""

    def part_recuperable(self, montant):
        self.ensure_one()
        if self.recuperable == "oui":
            return montant
        if self.recuperable == "partiel":
            return round(montant * (self.taux_recuperable or 0.0) / 100.0, 2)
        return 0.0
