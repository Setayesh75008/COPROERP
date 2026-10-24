from collections import OrderedDict

from odoo import models


def _r(valeur):
    return round(valeur or 0.0, 2)


class BudgetAnnuel(models.Model):
    """Relevé général des dépenses de l'exercice, par clé de répartition et par nature
    (pièce jointe à la convocation de l'assemblée qui approuve les comptes)."""

    _inherit = "coproerp.budget.annuel"

    def fmt_montant(self, valeur):
        """Montant au format français (1 234,56)."""
        return "{:,.2f}".format(valeur or 0.0).replace(",", "\u00a0").replace(".", ",")

    def action_imprimer_releve_depenses(self):
        self.ensure_one()
        self.copropriete_id._verifier_dossier()
        return self.env.ref("coproerp_regularisation.action_report_releve_depenses").report_action(self)

    def _lignes_releve(self):
        self.ensure_one()
        copro = self.copropriete_id
        company = copro._verifier_dossier()
        MoveLine = self.env["account.move.line"].sudo()
        lignes = MoveLine.search([
            ("company_id", "=", company.id),
            ("parent_state", "=", "posted"),
            ("date", ">=", self.date_debut),
            ("date", "<=", self.date_fin),
            ("account_id.account_type", "in", ("expense", "expense_other", "income_other")),
        ], order="date, move_id, id")
        moves_regul = self.env["coproerp.regularisation"].sudo().search([
            ("budget_id", "=", self.id), ("etat", "=", "comptabilisee")]).move_id
        retenues = MoveLine
        for ligne in lignes:
            move = ligne.move_id
            # Factures annulées : l'écriture et sa contre-passation ne figurent pas au relevé
            annulee = move.reversed_entry_id or ("reversal_move_ids" in move._fields and move.reversal_move_ids)
            if move in moves_regul or annulee:
                continue
            code = ligne.account_id.with_company(company).code or ""
            if code.startswith("7") and not ligne.coproerp_repartition_id:
                continue  # produits sans clé : provisions, subventions… (hors relevé des charges)
            retenues |= ligne
        return retenues, company

    def donnees_releve_depenses(self):
        self.ensure_one()
        lignes, company = self._lignes_releve()
        natures = {n.code: n for n in self.env["coproerp.nature.depense"].with_context(active_test=False).search([])}

        def nouvelle_section():
            return {"natures": OrderedDict(), "tva": 0.0, "montant": 0.0, "recuperable": 0.0}

        courant = OrderedDict()   # clé -> section
        travaux = OrderedDict()   # opération -> section
        for ligne in lignes.sorted(lambda l: (l.account_id.with_company(company).code or "", l.date, l.id)):
            code = ligne.account_id.with_company(company).code or ""
            nature = natures.get(code)
            montant = _r(ligne.balance)
            ligne_facture = ligne.coproerp_depense_ligne_id
            tva = _r(ligne_facture.montant_tva) if ligne_facture else 0.0
            if ligne.coproerp_hors_budget:
                cle = ligne.coproerp_travaux_id
                section = travaux.setdefault(cle, nouvelle_section())
            else:
                cle = ligne.coproerp_repartition_id
                section = courant.setdefault(cle, nouvelle_section())
            groupe = section["natures"].setdefault(code, {
                "code": code,
                "libelle": nature.name if nature else ligne.account_id.name,
                "recuperable": nature.libelle_recuperable() if nature else "",
                "lignes": [], "tva": 0.0, "montant": 0.0,
            })
            depense = ligne.move_id.coproerp_depense_id
            libelle = " – ".join(x for x in [
                ligne.partner_id.name if ligne.partner_id else "",
                ligne_facture.designation if ligne_facture and ligne_facture.designation else (ligne.name or ""),
            ] if x)
            if depense and depense.reference_fournisseur:
                libelle += " (fact. %s)" % depense.reference_fournisseur
            recuperable = nature.part_recuperable(montant) if nature else 0.0
            groupe["lignes"].append({"date": ligne.date, "libelle": libelle, "tva": tva, "montant": montant})
            groupe["tva"] += tva
            groupe["montant"] += montant
            section["tva"] += tva
            section["montant"] += montant
            section["recuperable"] += recuperable

        def finaliser(sections, libelle_vide):
            resultat = []
            for cle, section in sections.items():
                resultat.append({
                    "cle": cle,
                    "libelle": (cle.name if cle._name == "coproerp.repartition" else
                                "%s – %s" % (cle.reference, cle.name)) if cle else libelle_vide,
                    "natures": [dict(g, tva=_r(g["tva"]), montant=_r(g["montant"])) for g in section["natures"].values()],
                    "tva": _r(section["tva"]), "montant": _r(section["montant"]),
                    "recuperable": _r(section["recuperable"]),
                })
            return sorted(resultat, key=lambda s: s["libelle"] or "")

        courant_l = finaliser(courant, "Charges sans clé de répartition")
        travaux_l = finaliser(travaux, "Opérations exceptionnelles non rattachées")
        total = {
            "courant_tva": _r(sum(s["tva"] for s in courant_l)),
            "courant": _r(sum(s["montant"] for s in courant_l)),
            "courant_recuperable": _r(sum(s["recuperable"] for s in courant_l)),
            "travaux_tva": _r(sum(s["tva"] for s in travaux_l)),
            "travaux": _r(sum(s["montant"] for s in travaux_l)),
        }
        total["immeuble_tva"] = _r(total["courant_tva"] + total["travaux_tva"])
        total["immeuble"] = _r(total["courant"] + total["travaux"])
        return {
            "budget": self,
            "copro": self.copropriete_id.sudo(),
            "courant": courant_l,
            "travaux": travaux_l,
            "total": total,
            "projet": not self._est_regularise(),
        }
