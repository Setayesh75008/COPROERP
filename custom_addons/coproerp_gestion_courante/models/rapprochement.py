import base64
import csv
import io
import re
import unicodedata
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

TOLERANCE_JOURS = 7


def normaliser(texte):
    """Majuscules sans accents, pour comparer les libellés bancaires aux noms."""
    texte = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9 ]+", " ", texte.upper())


def lire_montant(texte):
    texte = (texte or "").strip().replace(" ", "").replace(" ", "").replace("€", "").replace("EUR", "")
    if not texte:
        return 0.0
    if "," in texte and "." in texte:
        texte = texte.replace(".", "").replace(",", ".") if texte.rfind(",") > texte.rfind(".") else texte.replace(",", "")
    else:
        texte = texte.replace(",", ".")
    return float(texte)


def lire_date(texte):
    texte = (texte or "").strip()
    for format_date in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y%m%d"):
        try:
            return datetime.strptime(texte[:10] if format_date != "%Y%m%d" else texte[:8], format_date).date()
        except ValueError:
            continue
    return None


def analyser_csv(contenu):
    """Lignes (date, libellé, montant) d'un relevé CSV : séparateur « ; » ou « , », colonnes « montant »
    ou « débit » / « crédit », en-tête repéré automatiquement."""
    for encodage in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texte = contenu.decode(encodage)
            break
        except UnicodeDecodeError:
            continue
    separateur = ";" if texte.count(";") >= texte.count(",") else ","
    lignes = list(csv.reader(io.StringIO(texte), delimiter=separateur))
    entete_index, colonnes = None, {}
    for index, ligne in enumerate(lignes):
        noms = [normaliser(c).strip() for c in ligne]
        if any(n.startswith("DATE") for n in noms) and any(
                n.startswith(("MONTANT", "DEBIT", "CREDIT")) for n in noms):
            entete_index = index
            for position, nom in enumerate(noms):
                if nom.startswith("DATE") and "date" not in colonnes:
                    colonnes["date"] = position
                elif nom.startswith(("LIBELLE", "DESCRIPTION", "OPERATION", "INTITULE")) and "libelle" not in colonnes:
                    colonnes["libelle"] = position
                elif nom.startswith("MONTANT"):
                    colonnes["montant"] = position
                elif nom.startswith("DEBIT"):
                    colonnes["debit"] = position
                elif nom.startswith("CREDIT"):
                    colonnes["credit"] = position
            break
    if entete_index is None:
        raise UserError("Relevé CSV non reconnu : la ligne d'en-tête doit contenir « Date » et « Montant » "
                        "(ou « Débit » / « Crédit »).")
    resultat = []
    for ligne in lignes[entete_index + 1:]:
        if not ligne or len(ligne) <= colonnes["date"]:
            continue
        date = lire_date(ligne[colonnes["date"]])
        if not date:
            continue

        def valeur(cle):
            position = colonnes.get(cle)
            return ligne[position] if position is not None and position < len(ligne) else ""

        if "montant" in colonnes:
            montant = lire_montant(valeur("montant"))
        else:
            montant = lire_montant(valeur("credit")) - abs(lire_montant(valeur("debit")))
        resultat.append({"date": date, "libelle": valeur("libelle").strip(), "montant": round(montant, 2)})
    return resultat, None


def analyser_ofx(contenu):
    """Lignes et solde final d'un relevé OFX (format SGML ou XML)."""
    texte = contenu.decode("latin-1")

    def balise(bloc, nom):
        trouve = re.search(r"<%s>([^<\r\n]*)" % nom, bloc, re.IGNORECASE)
        return trouve.group(1).strip() if trouve else ""

    resultat = []
    for bloc in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|</BANKTRANLIST>)", texte, re.S | re.I):
        date = lire_date(balise(bloc, "DTPOSTED"))
        if not date:
            continue
        libelle = " ".join(x for x in (balise(bloc, "NAME"), balise(bloc, "MEMO")) if x)
        resultat.append({"date": date, "libelle": libelle, "montant": round(lire_montant(balise(bloc, "TRNAMT")), 2),
                         "reference": balise(bloc, "FITID")})
    solde = re.search(r"<LEDGERBAL>.*?<BALAMT>([^<\r\n]*)", texte, re.S | re.I)
    return resultat, (lire_montant(solde.group(1)) if solde else None)


class ReleveBancaire(models.Model):
    """Relevé du compte bancaire séparé du syndicat, à rapprocher de la comptabilité."""

    _name = "coproerp.releve.bancaire"
    _description = "Relevé bancaire"
    _inherit = ["mail.thread"]
    _order = "date_fin desc, id desc"

    name = fields.Char(string="Numéro", readonly=True, copy=False, default="/")
    copropriete_id = fields.Many2one("coproerp.copropriete", string="Copropriété", required=True, index=True)
    date_debut = fields.Date(string="Du")
    date_fin = fields.Date(string="Au")
    solde_final = fields.Float(string="Solde final du relevé", digits=(16, 2), tracking=True)
    fichier = fields.Binary(string="Fichier du relevé (CSV ou OFX)")
    fichier_nom = fields.Char(string="Nom du fichier")
    ligne_ids = fields.One2many("coproerp.releve.bancaire.ligne", "releve_id", string="Opérations")
    etat = fields.Selection(
        [("brouillon", "En cours"), ("rapproche", "Rapproché")], string="État", default="brouillon",
        required=True, readonly=True, tracking=True)
    nombre_a_pointer = fields.Integer(string="Opérations à pointer", compute="_compute_stats")
    solde_comptable = fields.Float(string="Solde comptable du compte 512", compute="_compute_stats", digits=(16, 2))
    ecart = fields.Float(string="Écart à expliquer", compute="_compute_stats", digits=(16, 2))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("coproerp.releve.bancaire") or "/"
        return super().create(vals_list)

    @api.depends("ligne_ids.etat", "solde_final", "date_fin")
    def _compute_stats(self):
        for releve in self:
            releve.nombre_a_pointer = len(releve.ligne_ids.filtered(lambda l: l.etat == "a_pointer"))
            donnees = releve._donnees_etat() if releve.copropriete_id.company_id and releve.date_fin else None
            releve.solde_comptable = donnees["solde_comptable"] if donnees else 0.0
            releve.ecart = donnees["ecart"] if donnees else 0.0

    # ------------------------------------------------------------------
    def _compte_banque(self):
        return self.copropriete_id._journal("banque").default_account_id

    def action_importer(self):
        for releve in self:
            if not releve.fichier:
                raise UserError("Joignez le fichier du relevé (CSV ou OFX) exporté depuis la banque.")
            contenu = base64.b64decode(releve.fichier)
            nom = (releve.fichier_nom or "").lower()
            est_ofx = nom.endswith((".ofx", ".qfx")) or b"<OFX>" in contenu[:2000].upper()
            operations, solde = analyser_ofx(contenu) if est_ofx else analyser_csv(contenu)
            if not operations:
                raise UserError("Aucune opération trouvée dans le fichier.")
            existantes = {(l.date, round(l.montant, 2), l.libelle) for l in releve.ligne_ids}
            nouvelles = [op for op in operations if (op["date"], op["montant"], op["libelle"]) not in existantes]
            releve.write({"ligne_ids": [(0, 0, {
                "date": op["date"], "libelle": op["libelle"], "montant": op["montant"],
                "reference": op.get("reference") or False}) for op in nouvelles]})
            dates = [op["date"] for op in operations]
            vals = {"date_debut": releve.date_debut or min(dates), "date_fin": max(dates + [releve.date_fin or min(dates)])}
            if solde is not None:
                vals["solde_final"] = solde
            releve.write(vals)
            releve.message_post(body="%d opération(s) importée(s)." % len(nouvelles))
        return self.action_pointer_automatiquement()

    def _lignes_disponibles(self):
        """Écritures du compte bancaire non encore pointées sur un relevé."""
        company = self.copropriete_id._verifier_dossier()
        pointees = self.env["coproerp.releve.bancaire.ligne"].search([
            ("releve_id.copropriete_id", "=", self.copropriete_id.id), ("move_line_id", "!=", False)]).move_line_id
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id), ("account_id", "=", self._compte_banque().id),
            ("parent_state", "=", "posted")])
        return lignes - pointees

    def action_pointer_automatiquement(self):
        for releve in self:
            disponibles = releve._lignes_disponibles()
            for ligne in releve.ligne_ids.filtered(lambda l: l.etat == "a_pointer"):
                candidates = disponibles.filtered(
                    lambda m: abs(round(m.balance, 2) - ligne.montant) < 0.005
                    and abs((m.date - ligne.date).days) <= TOLERANCE_JOURS)
                if candidates:
                    meilleure = candidates.sorted(lambda m: abs((m.date - ligne.date).days))[0]
                    ligne.write({"move_line_id": meilleure.id, "etat": "pointe"})
                    disponibles -= meilleure
                else:
                    ligne._proposer()
        return True

    def action_marquer_rapproche(self):
        for releve in self:
            if releve.nombre_a_pointer:
                raise UserError("%d opération(s) restent à pointer." % releve.nombre_a_pointer)
            releve.etat = "rapproche"
        return True

    def action_rouvrir(self):
        self.write({"etat": "brouillon"})
        return True

    def action_imprimer_etat(self):
        return self.env.ref("coproerp_gestion_courante.action_report_etat_rapprochement").report_action(self)

    def _donnees_etat(self):
        """État de rapprochement à la date de fin du relevé."""
        self.ensure_one()
        company = self.copropriete_id.sudo()._verifier_dossier()
        lignes = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id), ("account_id", "=", self._compte_banque().id),
            ("parent_state", "=", "posted"), ("date", "<=", self.date_fin)])
        solde_comptable = round(sum(lignes.mapped("balance")), 2)
        pointees = self.env["coproerp.releve.bancaire.ligne"].search([
            ("releve_id.copropriete_id", "=", self.copropriete_id.id), ("move_line_id", "!=", False),
            ("date", "<=", self.date_fin)]).move_line_id
        # Les écritures antérieures au premier relevé importé (reprise des soldes…) sont réputées rapprochées.
        premiers = self.search([("copropriete_id", "=", self.copropriete_id.id), ("date_debut", "!=", False)])
        origine = min(premiers.mapped("date_debut")) if premiers else self.date_debut
        compta_non_pointees = (lignes - pointees).filtered(lambda m: not origine or m.date >= origine)
        releve_non_pointees = self.ligne_ids.filtered(lambda l: l.etat == "a_pointer")
        # Solde du relevé = solde comptable − écritures comptables absentes du relevé + opérations du relevé
        # non comptabilisées
        explique = round(solde_comptable - sum(compta_non_pointees.mapped("balance"))
                         + sum(releve_non_pointees.mapped("montant")), 2)
        return {
            "solde_comptable": solde_comptable,
            "compta_non_pointees": compta_non_pointees.sorted("date"),
            "releve_non_pointees": releve_non_pointees.sorted("date"),
            "solde_reconstitue": explique,
            "ecart": round(self.solde_final - explique, 2),
        }


class ReleveBancaireLigne(models.Model):
    _name = "coproerp.releve.bancaire.ligne"
    _description = "Opération d'un relevé bancaire"
    _order = "date, id"

    releve_id = fields.Many2one("coproerp.releve.bancaire", required=True, ondelete="cascade", index=True)
    copropriete_id = fields.Many2one(related="releve_id.copropriete_id", store=True)
    date = fields.Date(string="Date", required=True)
    libelle = fields.Char(string="Libellé")
    reference = fields.Char(string="Référence bancaire")
    montant = fields.Float(string="Montant", digits=(16, 2), required=True,
                           help="Positif : encaissement (crédit sur le relevé). Négatif : décaissement.")
    etat = fields.Selection(
        [("a_pointer", "À pointer"), ("pointe", "Pointée"), ("ignore", "Ignorée")],
        string="État", default="a_pointer", required=True)
    move_line_id = fields.Many2one("account.move.line", string="Écriture pointée", readonly=True)
    personne_id = fields.Many2one("res.partner", string="Copropriétaire proposé")
    depense_id = fields.Many2one(
        "coproerp.depense", string="Facture proposée",
        domain="[('copropriete_id', '=', copropriete_id), ('etat', '=', 'validee'), ('est_payee', '=', False)]")
    suggestion = fields.Char(string="Proposition", readonly=True)

    def _proposer(self):
        """Propose un copropriétaire (encaissement) ou une facture (décaissement) à partir du libellé."""
        for ligne in self:
            texte = normaliser(ligne.libelle)
            copro = ligne.releve_id.copropriete_id
            if ligne.montant > 0:
                lots = self.env["coproerp.lot"].search([("copropriete_id", "=", copro.id)])
                personnes = self.env["res.partner"]
                for lot in lots:
                    partner, _erreur = lot._destinataire_appels(ligne.date)
                    personnes |= partner
                trouve = personnes.filtered(lambda p: any(
                    len(mot) > 2 and mot in texte.split() for mot in normaliser(p.name).split()))
                if len(trouve) == 1:
                    ligne.write({"personne_id": trouve.id, "suggestion": "Règlement de %s" % trouve.name})
            else:
                factures = self.env["coproerp.depense"].search([
                    ("copropriete_id", "=", copro.id), ("etat", "=", "validee"), ("est_payee", "=", False)])
                trouve = factures.filtered(lambda d: abs(d.montant_restant + ligne.montant) < 0.005)
                if len(trouve) > 1:
                    trouve = trouve.filtered(lambda d: any(
                        len(mot) > 2 and mot in texte.split() for mot in normaliser(d.fournisseur_id.name).split())) or trouve
                if len(trouve) == 1:
                    ligne.write({"depense_id": trouve.id, "suggestion": "Paiement de %s (%s)" % (
                        trouve.name, trouve.fournisseur_id.name)})

    def _pointer_sur_move(self, move):
        compte = self.releve_id._compte_banque()
        ligne_banque = move.line_ids.filtered(lambda l: l.account_id == compte)[:1]
        self.write({"move_line_id": ligne_banque.id, "etat": "pointe"})

    def action_creer_reglement(self):
        for ligne in self:
            if ligne.etat != "a_pointer" or ligne.montant <= 0:
                raise UserError("Seul un encaissement non pointé peut devenir un règlement de copropriétaire.")
            if not ligne.personne_id:
                raise UserError("Indiquez le copropriétaire qui a payé.")
            reglement = self.env["coproerp.reglement"].create({
                "copropriete_id": ligne.copropriete_id.id, "personne_id": ligne.personne_id.id,
                "date": ligne.date, "montant": ligne.montant, "mode": "virement",
                "reference": ligne.libelle,
            })
            reglement.action_valider()
            ligne._pointer_sur_move(reglement.move_id)
        return True

    def action_creer_paiement(self):
        for ligne in self:
            if ligne.etat != "a_pointer" or ligne.montant >= 0:
                raise UserError("Seul un décaissement non pointé peut devenir un paiement de facture.")
            if not ligne.depense_id:
                raise UserError("Indiquez la facture payée.")
            paiement = self.env["coproerp.depense.paiement"].create({
                "depense_id": ligne.depense_id.id, "date": ligne.date, "montant": -ligne.montant,
                "mode": "virement", "reference": ligne.libelle,
            })
            paiement.action_valider()
            ligne._pointer_sur_move(paiement.move_id)
        return True

    def action_ignorer(self):
        self.write({"etat": "ignore"})
        return True

    def action_depointer(self):
        self.write({"etat": "a_pointer", "move_line_id": False})
        return True
