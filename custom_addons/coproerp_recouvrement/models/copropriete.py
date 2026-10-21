from odoo import fields, models


class Copropriete(models.Model):
    _inherit = "coproerp.copropriete"

    recouvrement_jours_avant_relance = fields.Integer(
        string="Relance après (jours de retard)", default=10,
        help="Nombre de jours après l'échéance impayée la plus ancienne avant la première relance.",
    )
    recouvrement_jours_avant_mise_en_demeure = fields.Integer(
        string="Mise en demeure après (jours depuis la relance)", default=15,
    )
    recouvrement_seuil = fields.Float(
        string="Seuil minimal de relance (€)", default=1.0, digits=(16, 2),
    )
    recouvrement_delai_mise_en_demeure = fields.Integer(
        string="Délai de paiement accordé par la mise en demeure (jours)", default=30,
        help="L'article 19-2 de la loi du 10 juillet 1965 rend les provisions non échues exigibles "
             "après une mise en demeure restée infructueuse pendant trente jours.",
    )
    recouvrement_frais_mise_en_demeure = fields.Float(
        string="Frais de mise en demeure (€ TTC)", digits=(16, 2), default=0.0,
        help="Montant prévu au contrat de syndic, imputé au seul copropriétaire défaillant "
             "(art. 10-1 de la loi du 10 juillet 1965). Laissez 0 pour ne rien imputer.",
    )
    recouvrement_cle_frais_id = fields.Many2one(
        "coproerp.repartition", string="Clé des honoraires de recouvrement",
        domain="[('copropriete_id', '=', id)]",
        help="Clé sur laquelle vous saisissez la facture d'honoraires du syndic pour la mise en "
             "demeure : les frais refacturés au copropriétaire viennent en déduction de cette clé "
             "lors de la régularisation, de sorte que les autres copropriétaires ne les supportent pas.",
    )

    def situation_debiteur(self, personne, date):
        """Solde exigible du copropriétaire à ``date`` et échéance impayée la plus ancienne.

        Les appels étant comptabilisés à leur date d'exigibilité, le solde des
        comptes 450 à une date est la somme exigible à cette date.
        """
        self.ensure_one()
        copro = self.sudo()
        date = fields.Date.to_date(date)
        lignes = copro._lignes_coproprietaires(personne.ids, date_max=date)
        solde = round(sum(lignes.mapped("debit")) - sum(lignes.mapped("credit")), 2)
        impayes = lignes.filtered(lambda l: l.debit and l.amount_residual > 0.005)
        plus_ancienne = min(impayes.mapped("date")) if impayes and solde > 0.005 else False
        return {
            "solde": solde,
            "plus_ancienne": plus_ancienne,
            "jours_retard": (date - plus_ancienne).days if plus_ancienne else 0,
        }

    def debiteurs(self, date):
        """Copropriétaires dont le compte est débiteur à ``date``."""
        self.ensure_one()
        lignes = self.sudo()._lignes_coproprietaires(date_max=date)
        soldes = {}
        for ligne in lignes:
            soldes[ligne.partner_id] = soldes.get(ligne.partner_id, 0.0) + ligne.debit - ligne.credit
        return self.env["res.partner"].browse(
            [p.id for p, s in soldes.items() if p and round(s, 2) > 0.005])
