import math
from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

COMPTE_COPRO_BUDGET = "450010"
COMPTE_PROVISIONS = "701000"


def repartir(total, parts_par_cle, total_parts, complet):
    """Répartit `total` (en euros) au prorata des parts, au centime près.

    Si toutes les parts de la clé sont attribuées (`complet`), les centimes
    d'arrondi sont distribués aux plus forts restes : la somme des quotes-parts
    est alors exactement égale au total.
    """
    if not total_parts or not parts_par_cle:
        return {cle: 0.0 for cle in parts_par_cle}
    centimes = round(total * 100)
    signe = -1 if centimes < 0 else 1
    centimes = abs(centimes)
    exacts = {cle: centimes * parts / total_parts for cle, parts in parts_par_cle.items()}
    resultat = {cle: math.floor(valeur) for cle, valeur in exacts.items()}
    if complet:
        reste = centimes - sum(resultat.values())
        ordre = sorted(exacts, key=lambda c: (exacts[c] - resultat[c]), reverse=True)
        for cle in ordre[:reste]:
            resultat[cle] += 1
    return {cle: signe * valeur / 100.0 for cle, valeur in resultat.items()}


class Regularisation(models.Model):
    """Régularisation des charges d'un exercice.

    Pour chaque lot et chaque clé de répartition : quote-part des dépenses
    réelles de l'exercice (hors travaux décidés par l'assemblée) moins les
    provisions appelées sur le budget prévisionnel. Le solde est porté au
    compte de celui qui est copropriétaire à la date d'attribution (en principe
    la date d'approbation des comptes : art. 6-2 du décret du 17 mars 1967).
    """

    _name = "coproerp.regularisation"
    _description = "Régularisation des charges de l'exercice"
    _inherit = ["mail.thread"]
    _order = "date_comptable desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="Libellé", compute="_compute_name", store=True)
    budget_id = fields.Many2one(
        "coproerp.budget.annuel", string="Exercice (budget)", required=True, index=True,
        ondelete="restrict", tracking=True,
    )
    copropriete_id = fields.Many2one(related="budget_id.copropriete_id", store=True, string="Copropriété")
    date_debut = fields.Date(related="budget_id.date_debut", string="Début de l'exercice")
    date_fin = fields.Date(related="budget_id.date_fin", string="Fin de l'exercice")
    date_comptable = fields.Date(
        string="Date de l'écriture", required=True,
        tracking=True, help="En principe, le dernier jour de l'exercice.",
    )
    date_attribution = fields.Date(
        string="Copropriétaire à la date du",
        required=True, tracking=True,
        help="Le solde de la régularisation est porté au compte de celui qui est copropriétaire "
        "à cette date, en principe celle de l'approbation des comptes par l'assemblée "
        "(art. 6-2 du décret du 17 mars 1967).",
    )
    etat = fields.Selection(
        [
            ("brouillon", "Brouillon"),
            ("calculee", "Calculée"),
            ("comptabilisee", "Comptabilisée"),
            ("annulee", "Annulée"),
        ],
        string="État", default="brouillon", required=True, readonly=True, copy=False, tracking=True,
    )
    ligne_ids = fields.One2many("coproerp.regularisation.ligne", "regularisation_id", string="Détail par lot et par clé")
    compte_ids = fields.One2many("coproerp.regularisation.compte", "regularisation_id", string="Par copropriétaire")
    total_depenses = fields.Float(string="Dépenses réparties", compute="_compute_totaux", digits=(16, 2))
    total_provisions = fields.Float(string="Provisions appelées", compute="_compute_totaux", digits=(16, 2))
    total_solde = fields.Float(string="Solde à régulariser", compute="_compute_totaux", digits=(16, 2))
    move_id = fields.Many2one("account.move", string="Écriture", readonly=True, copy=False)
    move_annulation_id = fields.Many2one("account.move", string="Écriture d'annulation", readonly=True, copy=False)
    avertissement = fields.Text(string="Points d'attention", readonly=True, copy=False)

    @api.depends("budget_id")
    def _compute_name(self):
        for regul in self:
            budget = regul.budget_id
            regul.name = "Régularisation des charges %s – %s" % (
                budget.exercice or "", budget.copropriete_id.name or ""
            )

    @api.onchange("budget_id")
    def _onchange_budget_id(self):
        if self.budget_id.date_fin:
            self.date_comptable = self.budget_id.date_fin
            self.date_attribution = self.budget_id.date_fin

    @api.model_create_multi
    def create(self, vals_list):
        # Dates par défaut : dernier jour de l'exercice
        for vals in vals_list:
            if vals.get("budget_id") and not (vals.get("date_comptable") and vals.get("date_attribution")):
                fin = self.env["coproerp.budget.annuel"].browse(vals["budget_id"]).date_fin
                vals.setdefault("date_comptable", fin)
                vals.setdefault("date_attribution", fin)
        return super().create(vals_list)

    @api.depends("compte_ids.charges", "compte_ids.provisions", "compte_ids.solde")
    def _compute_totaux(self):
        for regul in self:
            regul.total_depenses = round(sum(regul.compte_ids.mapped("charges")), 2)
            regul.total_provisions = round(sum(regul.compte_ids.mapped("provisions")), 2)
            regul.total_solde = round(sum(regul.compte_ids.mapped("solde")), 2)

    @api.constrains("budget_id", "etat")
    def _check_unique(self):
        for regul in self.filtered(lambda r: r.etat != "annulee"):
            if self.search_count([
                ("id", "!=", regul.id), ("budget_id", "=", regul.budget_id.id), ("etat", "!=", "annulee"),
            ]):
                raise ValidationError(
                    "Une régularisation existe déjà pour cet exercice : annulez-la avant d'en créer une autre."
                )

    def unlink(self):
        if self.filtered(lambda r: r.etat in ("comptabilisee", "annulee")):
            raise UserError("Une régularisation comptabilisée ne peut pas être supprimée : annulez-la.")
        return super().unlink()

    # ------------------------------------------------------------------
    # Calcul
    # ------------------------------------------------------------------
    def _depenses_par_cle(self):
        """{clé: {compte: (libellé, montant)}} des dépenses de l'exercice."""
        self.ensure_one()
        budget = self.budget_id
        company = self.copropriete_id._verifier_dossier()
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "in", ("expense", "expense_other")),
            ("coproerp_hors_budget", "=", False),
            ("date", ">=", budget.date_debut),
            ("date", "<=", budget.date_fin),
        ])
        sans_cle = lignes.filtered(lambda l: not l.coproerp_repartition_id)
        if sans_cle:
            raise UserError(
                "%d ligne(s) de charges de l'exercice n'ont pas de clé de répartition (écritures "
                "saisies hors des factures fournisseurs). Exemple : %s du %s."
                % (len(sans_cle), sans_cle[0].name or sans_cle[0].move_id.ref or "",
                   sans_cle[0].date.strftime("%d/%m/%Y"))
            )
        resultat = defaultdict(dict)
        for ligne in lignes:
            compte = ligne.account_id.with_company(company)
            cle = ligne.coproerp_repartition_id
            libelle, montant = resultat[cle].get(compte.code, (compte.name, 0.0))
            resultat[cle][compte.code] = (libelle, montant + ligne.balance)
        return resultat

    def _provisions_par_lot_et_cle(self):
        self.ensure_one()
        budget = self.budget_id
        postes = self.env["coproerp.appel.charge.poste"].sudo().search([
            ("appel_id.copropriete_id", "=", self.copropriete_id.id),
            ("appel_id.type_appel", "=", "budget_courant"),
            ("appel_id.etat_comptable", "=", "comptabilise"),
            "|",
            ("appel_id.budget_origine_id", "=", budget.id),
            ("appel_id.budget_id", "=", budget.id),
        ])
        resultat = defaultdict(float)
        for poste in postes:
            resultat[(poste.lot_id, poste.repartition_id)] += poste.montant_appel
        return resultat

    def action_calculer(self):
        for regul in self:
            if regul.etat not in ("brouillon", "calculee"):
                raise UserError("Seule une régularisation non comptabilisée peut être recalculée.")
            regul._calculer()
        return True

    def _calculer(self):
        self.ensure_one()
        depenses = self._depenses_par_cle()
        provisions = self._provisions_par_lot_et_cle()
        self.compte_ids.unlink()
        self.ligne_ids.unlink()

        avertissements = []
        cles = set(depenses) | {cle for (_lot, cle) in provisions}
        valeurs_lignes = []
        for cle in sorted(cles, key=lambda c: c.name or ""):
            parts = {rl.lot_id: rl.tantiemes for rl in cle.line_ids if rl.lot_id and rl.tantiemes}
            total_parts = cle.total_tantiemes
            complet = sum(parts.values()) == total_parts
            natures = depenses.get(cle, {})
            total_cle = round(sum(m for _l, m in natures.values()), 2)
            if not complet and natures:
                avertissements.append(
                    "Clé « %s » : %s tantièmes attribués sur %s ; la part non attribuée des dépenses "
                    "reste à la charge du syndicat." % (cle.name, sum(parts.values()), total_parts)
                )
            # Répartition nature par nature (au centime près)
            par_lot = defaultdict(list)
            for code, (libelle, montant) in sorted(natures.items()):
                for lot, quote in repartir(montant, parts, total_parts, complet).items():
                    par_lot[lot].append((code, libelle, round(montant, 2), quote))
            lots = set(parts) | {lot for (lot, c) in provisions if c == cle}
            for lot in sorted(lots, key=lambda l: (l.numero or "")):
                if lot.propriete_syndicat:
                    continue
                details = par_lot.get(lot, [])
                quote_part = round(sum(d[3] for d in details), 2)
                provision = round(provisions.get((lot, cle), 0.0), 2)
                valeurs_lignes.append({
                    "regularisation_id": self.id,
                    "lot_id": lot.id,
                    "repartition_id": cle.id,
                    "parts": parts.get(lot, 0),
                    "total_parts": total_parts,
                    "depenses_cle": total_cle,
                    "quote_part": quote_part,
                    "provisions": provision,
                    "detail_ids": [Command.create({
                        "code": code, "libelle": libelle, "total": total, "quote_part": quote,
                    }) for code, libelle, total, quote in details],
                })
        lignes = self.env["coproerp.regularisation.ligne"].create(valeurs_lignes)

        # Destinataires (art. 6-2 du décret de 1967)
        erreurs = []
        destinataires = {}
        for lot in lignes.lot_id:
            personne, erreur = lot._destinataire_appels(self.date_attribution)
            if erreur:
                erreurs.append(erreur)
            elif not personne:
                erreurs.append("Lot %s : aucun copropriétaire au %s."
                               % (lot.numero, self.date_attribution.strftime("%d/%m/%Y")))
            destinataires[lot] = personne
        if erreurs:
            raise UserError("Impossible de déterminer le copropriétaire de certains lots :\n- "
                            + "\n- ".join(erreurs))
        for ligne in lignes:
            ligne.personne_id = destinataires[ligne.lot_id]

        par_personne = defaultdict(lambda: self.env["coproerp.regularisation.ligne"])
        for ligne in lignes:
            par_personne[ligne.personne_id] |= ligne
        self.env["coproerp.regularisation.compte"].create([{
            "regularisation_id": self.id,
            "personne_id": personne.id,
            "ligne_ids": [Command.set(lignes_p.ids)],
        } for personne, lignes_p in par_personne.items()])
        self.write({"etat": "calculee", "avertissement": "\n".join(avertissements) or False})

    def action_remettre_brouillon(self):
        for regul in self.filtered(lambda r: r.etat == "calculee"):
            regul.compte_ids.unlink()
            regul.ligne_ids.unlink()
            regul.write({"etat": "brouillon", "avertissement": False})
        return True

    # ------------------------------------------------------------------
    # Comptabilisation
    # ------------------------------------------------------------------
    def action_comptabiliser(self):
        for regul in self.filtered(lambda r: r.etat == "calculee"):
            company = regul.copropriete_id._verifier_dossier()
            regul = regul.with_company(company)
            copro = regul.copropriete_id
            arrondi = company.currency_id.round
            compte_copro = copro._compte(COMPTE_COPRO_BUDGET)
            libelle = "Régularisation des charges %s" % (regul.budget_id.exercice or "")
            commandes = []
            total = 0.0
            for compte in regul.compte_ids:
                solde = arrondi(compte.solde)
                if not solde:
                    continue
                total += solde
                commandes.append(Command.create({
                    "account_id": compte_copro.id,
                    "partner_id": compte.personne_id.id,
                    "name": libelle,
                    "debit": solde if solde > 0 else 0.0,
                    "credit": -solde if solde < 0 else 0.0,
                    "date_maturity": regul.date_attribution,
                }))
            total = arrondi(total)
            if total:
                commandes.append(Command.create({
                    "account_id": copro._compte(COMPTE_PROVISIONS).id,
                    "name": libelle,
                    "debit": -total if total < 0 else 0.0,
                    "credit": total if total > 0 else 0.0,
                }))
            move = self.env["account.move"]
            if commandes:
                move = self.env["account.move"].with_company(company).create({
                    "move_type": "entry",
                    "journal_id": copro._journal("od").id,
                    "date": regul.date_comptable,
                    "ref": "%s – %s" % (libelle, copro.name),
                    "line_ids": commandes,
                })
                move.action_post()
                regul._lettrer(move, compte_copro)
            regul.write({"move_id": move.id or False, "etat": "comptabilisee"})
        return True

    def _lettrer(self, move, compte_copro):
        """Impute le solde de régularisation sur les sommes dues ou versées d'avance."""
        MoveLine = self.env["account.move.line"]
        for ligne in move.line_ids.filtered(lambda l: l.account_id == compte_copro):
            signe = "<" if ligne.balance > 0 else ">"
            opposees = MoveLine.search([
                ("company_id", "=", move.company_id.id),
                ("account_id", "=", compte_copro.id),
                ("partner_id", "=", ligne.partner_id.id),
                ("parent_state", "=", "posted"),
                ("reconciled", "=", False),
                ("amount_residual", signe, 0),
                ("id", "!=", ligne.id),
            ], order="date_maturity, date, id")
            if opposees:
                (ligne | opposees).reconcile()

    def action_annuler(self):
        for regul in self.filtered(lambda r: r.etat == "comptabilisee"):
            if regul.move_id:
                regul = regul.with_company(regul.copropriete_id._verifier_dossier())
                date = max(fields.Date.context_today(self), regul.move_id.date)
                annulation = regul.move_id._reverse_moves(
                    [{"date": date, "ref": "Annulation %s" % (regul.move_id.ref or "")}], cancel=True
                )
                regul.move_annulation_id = annulation
            regul.etat = "annulee"
        return True

    def action_imprimer_decomptes(self):
        self.ensure_one()
        if not self.compte_ids:
            raise UserError("Calculez d'abord la régularisation.")
        return self.env.ref("coproerp_regularisation.action_report_decompte").report_action(self.compte_ids)


class RegularisationLigne(models.Model):
    _name = "coproerp.regularisation.ligne"
    _description = "Régularisation : un lot pour une clé de répartition"
    _order = "repartition_id, lot_id"

    regularisation_id = fields.Many2one("coproerp.regularisation", required=True, ondelete="cascade", index=True)
    lot_id = fields.Many2one("coproerp.lot", string="Lot", required=True)
    personne_id = fields.Many2one("res.partner", string="Copropriétaire")
    repartition_id = fields.Many2one("coproerp.repartition", string="Clé de répartition", required=True)
    parts = fields.Integer(string="Tantièmes du lot")
    total_parts = fields.Integer(string="Total des tantièmes")
    depenses_cle = fields.Float(string="Dépenses de la clé", digits=(16, 2))
    quote_part = fields.Float(string="Quote-part des dépenses", digits=(16, 2))
    provisions = fields.Float(string="Provisions appelées", digits=(16, 2))
    solde = fields.Float(string="Solde", compute="_compute_solde", store=True, digits=(16, 2))
    detail_ids = fields.One2many("coproerp.regularisation.detail", "ligne_id", string="Détail par nature")

    @api.depends("quote_part", "provisions")
    def _compute_solde(self):
        for ligne in self:
            ligne.solde = round(ligne.quote_part - ligne.provisions, 2)


class RegularisationDetail(models.Model):
    _name = "coproerp.regularisation.detail"
    _description = "Régularisation : détail par nature de dépense"
    _order = "code"

    ligne_id = fields.Many2one("coproerp.regularisation.ligne", required=True, ondelete="cascade", index=True)
    code = fields.Char(string="Compte")
    libelle = fields.Char(string="Nature")
    total = fields.Float(string="Total de la nature", digits=(16, 2))
    quote_part = fields.Float(string="Quote-part du lot", digits=(16, 2))


class RegularisationCompte(models.Model):
    _name = "coproerp.regularisation.compte"
    _description = "Régularisation : décompte d'un copropriétaire"
    _order = "personne_id"
    _rec_name = "personne_id"

    regularisation_id = fields.Many2one("coproerp.regularisation", required=True, ondelete="cascade", index=True)
    personne_id = fields.Many2one("res.partner", string="Copropriétaire", required=True)
    ligne_ids = fields.Many2many(
        "coproerp.regularisation.ligne", "coproerp_regul_compte_ligne_rel", "compte_id", "ligne_id",
        string="Lignes",
    )
    charges = fields.Float(string="Charges réelles", compute="_compute_montants", store=True, digits=(16, 2))
    provisions = fields.Float(string="Provisions appelées", compute="_compute_montants", store=True, digits=(16, 2))
    solde = fields.Float(string="Solde", compute="_compute_montants", store=True, digits=(16, 2),
                         help="Positif : complément à régler. Négatif : somme en faveur du copropriétaire.")

    @api.depends("ligne_ids.quote_part", "ligne_ids.provisions")
    def _compute_montants(self):
        for compte in self:
            compte.charges = round(sum(compte.ligne_ids.mapped("quote_part")), 2)
            compte.provisions = round(sum(compte.ligne_ids.mapped("provisions")), 2)
            compte.solde = round(compte.charges - compte.provisions, 2)

    def donnees_decompte(self):
        """Données du décompte individuel (rapport PDF)."""
        self.ensure_one()
        regul = self.regularisation_id
        sections = []
        for cle in self.ligne_ids.repartition_id.sorted(lambda c: c.name or ""):
            lignes = self.ligne_ids.filtered(lambda l: l.repartition_id == cle)
            # Une seule ligne par nature, même si la personne a plusieurs lots
            natures = {}
            for ligne in lignes:
                for detail in ligne.detail_ids:
                    entree = natures.setdefault(detail.code, {
                        "code": detail.code, "libelle": detail.libelle, "total": detail.total,
                        "quote_part": 0.0,
                    })
                    entree["quote_part"] += detail.quote_part
            sections.append({
                "cle": cle,
                "total_parts": lignes[:1].total_parts,
                "parts": sum(lignes.mapped("parts")),
                "natures": sorted(natures.values(), key=lambda n: n["code"]),
                "depenses_cle": lignes[:1].depenses_cle,
                "quote_part": round(sum(lignes.mapped("quote_part")), 2),
                "provisions": round(sum(lignes.mapped("provisions")), 2),
                "solde": round(sum(lignes.mapped("solde")), 2),
            })
        return {
            "regul": regul,
            "copro": regul.copropriete_id.sudo(),
            "personne": self.personne_id,
            "lots": self.ligne_ids.lot_id.sorted(lambda l: l.numero or ""),
            "sections": sections,
            "charges": self.charges,
            "provisions": self.provisions,
            "solde": self.solde,
            "projet": regul.etat != "comptabilisee",
        }
