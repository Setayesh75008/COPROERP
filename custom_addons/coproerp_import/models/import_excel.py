import base64
import io

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from . import lecture

TYPES_TITULAIRES = ("proprietaire", "indivisaire", "usufruitier", "nu_proprietaire")
BATIMENT_PAR_DEFAUT = "Bâtiment principal"


class ImportExcel(models.Model):
    """Import d'un classeur Excel : lots, copropriétaires, tantièmes et soldes d'une copropriété."""

    _name = "coproerp.import.excel"
    _description = "Import Excel d'une copropriété"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(string="Libellé", compute="_compute_name", store=True)
    copropriete_id = fields.Many2one(
        "coproerp.copropriete", string="Copropriété", required=True, index=True, ondelete="cascade",
        help="Créez d'abord la fiche de la copropriété (nom, adresse) : l'import y ajoute les lots, les "
             "copropriétaires, les tantièmes et les soldes.")
    fichier = fields.Binary(string="Classeur Excel (.xlsx)", attachment=True)
    fichier_nom = fields.Char(string="Nom du fichier")
    sens_solde = fields.Selection(
        [("negatif_debiteur", "Un solde négatif signifie que le copropriétaire doit de l'argent"),
         ("positif_debiteur", "Un solde positif signifie que le copropriétaire doit de l'argent")],
        string="Sens des soldes du fichier",
        help="Les logiciels n'utilisent pas tous la même convention. Vérifiez sur un copropriétaire dont vous "
             "connaissez la situation (par exemple un débiteur relancé) avant d'importer.")
    date_reprise = fields.Date(
        string="Soldes arrêtés au",
        help="Date de l'état des soldes de l'ancien syndic : elle devient la date de la reprise des soldes.")
    etat = fields.Selection(
        [("brouillon", "À analyser"), ("analyse", "Analysé"), ("importe", "Importé")],
        string="État", default="brouillon", required=True, readonly=True, tracking=True)
    nombre_anomalies = fields.Integer(string="Anomalies bloquantes", readonly=True)
    rapport = fields.Text(string="Résultat de l'analyse", readonly=True)
    journal = fields.Text(string="Compte rendu de l'import", readonly=True)
    reprise_id = fields.Many2one("coproerp.reprise", string="Reprise des soldes", readonly=True)
    modele = fields.Binary(string="Modèle", readonly=True, attachment=False)

    @api.depends("copropriete_id", "fichier_nom")
    def _compute_name(self):
        for imp in self:
            imp.name = "Import %s%s" % (imp.copropriete_id.name or "", " – %s" % imp.fichier_nom if imp.fichier_nom else "")

    @api.onchange("fichier")
    def _onchange_fichier(self):
        if self.etat != "importe":
            self.etat = "brouillon"

    # ------------------------------------------------------------------
    # Analyse : lecture du fichier et plan d'import, sans rien créer
    # ------------------------------------------------------------------
    def _lire(self):
        self.ensure_one()
        if not self.fichier:
            raise UserError("Joignez le classeur Excel.")
        try:
            return lecture.lire_classeur(base64.b64decode(self.fichier))
        except ValueError as erreur:
            raise UserError(str(erreur)) from None

    def _plan(self):
        """Prépare l'import : (plan, anomalies bloquantes, avertissements)."""
        self.ensure_one()
        donnees, lues = self._lire()
        copro = self.copropriete_id
        bloquantes = [a for a in lues if a[1]]
        avertissements = ["%s : %s" % (f, m) for f, ligne, m in lues if not ligne]
        Lot = self.env["coproerp.lot"].with_context(active_test=False)
        lots_base = {l.numero: l for l in Lot.search([("copropriete_id", "=", copro.id)])}
        lots_fichier = {}
        for lot in donnees["lots"]:
            if lot["numero"] in lots_fichier:
                bloquantes.append(("Lots", lot["ligne"], "Lot %s en double dans le fichier." % lot["numero"]))
            lots_fichier[lot["numero"]] = lot
        numeros = set(lots_base) | set(lots_fichier)

        # Copropriétaires
        Partner = self.env["res.partner"].with_context(active_test=False)
        personnes, comptes = [], {}
        for ligne in donnees["coproprietaires"]:
            if ligne["compte"] and ligne["compte"] in comptes:
                bloquantes.append(("Copropriétaires", ligne["ligne"], "N° de compte %s en double." % ligne["compte"]))
            comptes[ligne["compte"]] = ligne
            existant = Partner.search([("ref", "=", ligne["compte"])], limit=1) if ligne["compte"] else Partner
            if not existant:
                existant = self._titulaires_copro().filtered(
                    lambda p: lecture.normaliser(p.name) == lecture.normaliser(ligne["nom"]))[:1]
            droit = lecture.type_droit(ligne["droit"])
            if droit is None:
                bloquantes.append(("Copropriétaires", ligne["ligne"], "Type de droit « %s » inconnu (propriétaire, "
                                   "usufruitier, nu-propriétaire, indivisaire, locataire)." % ligne["droit"]))
            if not ligne["lots"]:
                bloquantes.append(("Copropriétaires", ligne["ligne"], "%s : aucun lot indiqué." % ligne["nom"]))
            for numero in ligne["lots"]:
                if numero not in numeros:
                    bloquantes.append(("Copropriétaires", ligne["ligne"], "%s : lot %s inconnu (ni dans la feuille "
                                       "des lots ni dans la copropriété)." % (ligne["nom"], numero)))
            if not 0 < ligne["quotite"] <= 100:
                bloquantes.append(("Copropriétaires", ligne["ligne"], "%s : quote-part %s hors de 0-100 %%."
                                   % (ligne["nom"], ligne["quotite"])))
            personnes.append(dict(ligne, partner=existant, type_droit=droit))

        # Plusieurs titulaires sans mandataire commun
        titulaires_par_lot = {}
        for p in personnes:
            if p["type_droit"] in TYPES_TITULAIRES:
                for numero in p["lots"]:
                    titulaires_par_lot.setdefault(numero, []).append(p)
        for numero, liste in sorted(titulaires_par_lot.items()):
            if len(liste) > 1 and not any(p["mandataire"] for p in liste):
                avertissements.append("Lot %s : %d titulaires (%s) sans mandataire commun ; indiquez-le dans la "
                                      "colonne « Mandataire commun » ou sur la fiche du lot avant les appels de fonds."
                                      % (numero, len(liste), ", ".join(p["nom"] for p in liste)))

        # Tantièmes
        tantiemes = {}
        for ligne in donnees["tantiemes"]["lignes"]:
            if ligne["numero"] not in numeros:
                bloquantes.append(("Tantièmes", ligne["ligne"], "Lot %s inconnu." % ligne["numero"]))
                continue
            for cle, valeur in ligne["valeurs"].items():
                precedent = tantiemes.setdefault(cle, {}).get(ligne["numero"])
                if precedent is not None and precedent != valeur:
                    bloquantes.append(("Tantièmes", ligne["ligne"], "Lot %s, clé %s : deux valeurs différentes (%s et %s)."
                                       % (ligne["numero"], cle, precedent, valeur)))
                tantiemes[cle][ligne["numero"]] = valeur
        Repartition = self.env["coproerp.repartition"]
        cles = []
        for nom in donnees["tantiemes"]["cles"]:
            valeurs = tantiemes.get(nom, {})
            if not valeurs or not sum(valeurs.values()):
                avertissements.append("Clé « %s » : aucun tantième, ignorée." % nom)
                continue
            existante = Repartition.search([("copropriete_id", "=", copro.id), ("name", "=ilike", nom)], limit=1)
            cles.append({"nom": nom, "valeurs": valeurs, "repartition": existante, "total": sum(valeurs.values())})

        # Soldes
        soldes = []
        if donnees["soldes"]:
            if not self.sens_solde:
                bloquantes.append(("Soldes", 0, "Indiquez le sens des soldes du fichier (champ « Sens des soldes »)."))
            if not self.date_reprise:
                bloquantes.append(("Soldes", 0, "Indiquez la date d'arrêté des soldes."))
            reprise = self.env["coproerp.reprise"].search([("copropriete_id", "=", copro.id), ("etat", "=", "validee")],
                                                           limit=1)
            if reprise:
                bloquantes.append(("Soldes", 0, "La reprise des soldes de cette copropriété est déjà comptabilisée : "
                                   "annulez-la avant de réimporter des soldes."))
            signe = -1.0 if self.sens_solde == "negatif_debiteur" else 1.0
            vus = set()
            for ligne in donnees["soldes"]:
                entree = next((p for p in personnes if ligne["compte"] and p["compte"] == ligne["compte"]), None)
                if entree is None and ligne["nom"]:
                    entree = next((p for p in personnes
                                   if lecture.normaliser(p["nom"]) == lecture.normaliser(ligne["nom"])), None)
                partner = entree["partner"] if entree else Partner
                if entree is None:
                    if ligne["compte"]:
                        partner = Partner.search([("ref", "=", ligne["compte"])], limit=1)
                    if not partner and ligne["nom"]:
                        partner = self._titulaires_copro().filtered(
                            lambda p: lecture.normaliser(p.name) == lecture.normaliser(ligne["nom"]))[:1]
                    if not partner:
                        bloquantes.append(("Soldes", ligne["ligne"], "Copropriétaire %s %s introuvable : importez "
                                           "d'abord la feuille des copropriétaires avec le même n° de compte."
                                           % (ligne["compte"], ligne["nom"])))
                        continue
                cle = id(entree) if entree else partner.id
                if cle in vus:
                    bloquantes.append(("Soldes", ligne["ligne"], "%s figure deux fois dans les soldes."
                                       % (ligne["nom"] or ligne["compte"])))
                    continue
                vus.add(cle)
                if ligne["fonds_travaux"] < 0 or ligne["avance"] < 0:
                    bloquantes.append(("Soldes", ligne["ligne"], "%s : le fonds de travaux et l'avance ne peuvent pas "
                                       "être négatifs." % (ligne["nom"] or ligne["compte"])))
                soldes.append(dict(ligne, partner=partner, entree=entree, du=round(signe * ligne["solde"], 2)))

        batiments = sorted({l["batiment"] or BATIMENT_PAR_DEFAUT for l in lots_fichier.values()})
        plan = {
            "donnees": donnees, "lots_base": lots_base, "lots_fichier": lots_fichier, "personnes": personnes,
            "cles": cles, "soldes": soldes, "batiments": batiments,
        }
        return plan, bloquantes, avertissements

    def _titulaires_copro(self):
        lots = self.env["coproerp.lot"].search([("copropriete_id", "=", self.copropriete_id.id)])
        return lots.droit_ids.personne_id | lots.proprietaire_ids

    def _rapport(self, plan, bloquantes, avertissements):
        p = plan
        lots_nouveaux = [n for n in p["lots_fichier"] if n not in p["lots_base"]]
        lignes = ["Feuilles reconnues : %s" % (", ".join("« %s » (%s)" % f for f in p["donnees"]["feuilles"]) or "aucune")]
        if p["lots_fichier"]:
            lignes.append("Lots : %d dont %d nouveaux et %d mis à jour."
                          % (len(p["lots_fichier"]), len(lots_nouveaux), len(p["lots_fichier"]) - len(lots_nouveaux)))
        if p["personnes"]:
            nouveaux = len([x for x in p["personnes"] if not x["partner"]])
            lignes.append("Copropriétaires : %d dont %d nouveaux et %d déjà connus."
                          % (len(p["personnes"]), nouveaux, len(p["personnes"]) - nouveaux))
        for cle in p["cles"]:
            lignes.append("Clé « %s » : %d lots, total %d tantièmes%s." % (
                cle["nom"], len(cle["valeurs"]), cle["total"], " (clé existante mise à jour)" if cle["repartition"] else ""))
        if p["soldes"]:
            dus = sum(s["du"] for s in p["soldes"] if s["du"] > 0)
            avances = -sum(s["du"] for s in p["soldes"] if s["du"] < 0)
            lignes.append("Soldes : %d comptes ; dû par les copropriétaires débiteurs %s ; versé d'avance par les "
                          "créditeurs %s." % (len(p["soldes"]), _euros(dus), _euros(avances)))
            debiteurs = sorted((s for s in p["soldes"] if s["du"] > 0), key=lambda s: -s["du"])[:5]
            if debiteurs:
                lignes.append("   Principaux débiteurs : %s" % ", ".join(
                    "%s %s" % (s["nom"] or s["compte"], _euros(s["du"])) for s in debiteurs))
        if avertissements:
            lignes.append("")
            lignes.append("À vérifier :")
            lignes.extend("   – %s" % a for a in avertissements)
        if bloquantes:
            lignes.append("")
            lignes.append("ANOMALIES À CORRIGER DANS LE FICHIER (%d) :" % len(bloquantes))
            lignes.extend("   – %s%s : %s" % (f, " ligne %d" % l if l else "", m) for f, l, m in bloquantes)
        else:
            lignes.append("")
            lignes.append("Aucune anomalie bloquante : vous pouvez lancer l'import.")
        return "\n".join(lignes)

    def action_analyser(self):
        for imp in self:
            plan, bloquantes, avertissements = imp._plan()
            imp.write({"etat": "analyse" if imp.etat != "importe" else "importe",
                       "nombre_anomalies": len(bloquantes),
                       "rapport": imp._rapport(plan, bloquantes, avertissements)})
        return True

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def action_importer(self):
        self.ensure_one()
        plan, bloquantes, avertissements = self._plan()
        rapport = self._rapport(plan, bloquantes, avertissements)
        if bloquantes:
            self.write({"nombre_anomalies": len(bloquantes), "rapport": rapport, "etat": "analyse"})
            return True
        copro = self.copropriete_id
        compte_rendu = []

        # Bâtiments et lots
        Batiment = self.env["coproerp.batiment"].with_context(active_test=False)
        batiments = {b.name: b for b in Batiment.search([("copropriete_id", "=", copro.id)])}
        lots = dict(plan["lots_base"])
        for nom in plan["batiments"]:
            if nom == BATIMENT_PAR_DEFAUT and batiments and nom not in batiments:
                batiments[nom] = next(iter(batiments.values()))
            elif nom not in batiments:
                batiments[nom] = Batiment.create({"name": nom, "copropriete_id": copro.id})
        crees = maj = 0
        for numero, l in plan["lots_fichier"].items():
            usage = lecture.usage_lot(l["usage"] or l["designation"])
            vals = {
                "numero": numero,
                "designation": l["designation"] or (dict(self.env["coproerp.lot"]._fields["usage"].selection)
                                                    .get(usage, "Lot")),
                "batiment_id": batiments[l["batiment"] or BATIMENT_PAR_DEFAUT].id,
                "usage": usage, "type_lot": lecture.nature_lot(l["nature"], usage),
            }
            for champ in ("etage", "escalier"):
                if l[champ]:
                    vals[champ] = l[champ]
            if l["surface"]:
                vals["surface"] = l["surface"]
            if numero in lots:
                lots[numero].write(vals)
                maj += 1
            else:
                lots[numero] = self.env["coproerp.lot"].create(vals)
                crees += 1
        if plan["lots_fichier"]:
            compte_rendu.append("Lots : %d créés, %d mis à jour." % (crees, maj))

        # Copropriétaires et droits
        Partner = self.env["res.partner"]
        Droit = self.env["coproerp.droit"].with_context(active_test=False)
        crees = maj = droits = 0
        for p in plan["personnes"]:
            vals = {k: v for k, v in {
                "name": p["nom"], "ref": p["compte"] or False, "street": p["adresse"], "street2": p["adresse2"],
                "zip": p["code_postal"], "city": p["ville"], "email": p["email"], "phone": p["telephone"],
            }.items() if v}
            if p["type_droit"] == "locataire":
                vals["role_locataire"] = True
            else:
                vals["role_coproprietaire"] = True
            partner = p["partner"]
            if partner:
                partner.write(vals)
                maj += 1
            else:
                partner = Partner.create(dict(vals, is_company=False))
                p["partner"] = partner
                crees += 1
            for numero in p["lots"]:
                lot = lots[numero]
                droit = Droit.search([("lot_id", "=", lot.id), ("personne_id", "=", partner.id),
                                      ("type_droit", "=", p["type_droit"])], limit=1)
                vals_droit = {"quotite": p["quotite"], "active": True}
                if p["date"]:
                    vals_droit["date_debut"] = p["date"]
                if droit:
                    droit.write(vals_droit)
                else:
                    Droit.create(dict(vals_droit, lot_id=lot.id, personne_id=partner.id, type_droit=p["type_droit"]))
                    droits += 1
                if p["type_droit"] == "locataire":
                    lot.occupant_ids = [Command.link(partner.id)]
                else:
                    lot.proprietaire_ids = [Command.link(partner.id)]
                if p["mandataire"]:
                    lot.mandataire_commun_id = partner
        for s in plan["soldes"]:
            if s["entree"]:
                s["partner"] = s["entree"]["partner"]
        if plan["personnes"]:
            compte_rendu.append("Copropriétaires : %d créés, %d mis à jour ; %d droits sur lots créés."
                                % (crees, maj, droits))

        # Clés de répartition
        Repartition = self.env["coproerp.repartition"]
        Ligne = self.env["coproerp.repartition.lot"]
        for cle in plan["cles"]:
            repartition = cle["repartition"]
            if not repartition:
                repartition = Repartition.create({
                    "name": cle["nom"], "copropriete_id": copro.id, "type_repartition": lecture.type_cle(cle["nom"]),
                    "total_tantiemes": cle["total"]})
            existantes = {l.lot_id.numero: l for l in repartition.line_ids}
            for numero, valeur in cle["valeurs"].items():
                if numero in existantes:
                    existantes[numero].tantiemes = valeur
                elif valeur:
                    Ligne.create({"repartition_id": repartition.id, "lot_id": lots[numero].id, "tantiemes": valeur})
            repartition.total_tantiemes = sum(repartition.line_ids.mapped("tantiemes"))
            if repartition.type_repartition == "charges_generales":
                for numero, valeur in cle["valeurs"].items():
                    lots[numero].tantiemes = valeur
            compte_rendu.append("Clé « %s » : %d tantièmes répartis sur %d lots."
                                % (repartition.name, repartition.total_tantiemes, len(repartition.line_ids)))

        # Soldes → reprise des soldes (en brouillon, à compléter et comptabiliser)
        if plan["soldes"]:
            Reprise = self.env["coproerp.reprise"]
            reprise = Reprise.search([("copropriete_id", "=", copro.id), ("etat", "=", "brouillon")], limit=1)
            if reprise:
                reprise.write({"date_reprise": self.date_reprise})
            else:
                reprise = Reprise.create({"copropriete_id": copro.id, "date_reprise": self.date_reprise,
                                          "origine": "Import du fichier %s" % (self.fichier_nom or "")})
            colonnes = plan["donnees"]["colonnes_soldes"]
            presentes = {l.personne_id: l for l in reprise.coproprietaire_ids}
            commandes = []
            for s in plan["soldes"]:
                vals = {"solde": s["du"]}
                if "fonds_travaux" in colonnes:
                    vals["fonds_travaux"] = s["fonds_travaux"]
                if "avance" in colonnes:
                    vals["avance"] = s["avance"]
                ligne = presentes.get(s["partner"])
                if ligne:
                    commandes.append(Command.update(ligne.id, vals))
                else:
                    commandes.append(Command.create(dict(vals, personne_id=s["partner"].id)))
            reprise.write({"coproprietaire_ids": commandes})
            self.reprise_id = reprise
            compte_rendu.append("Reprise des soldes au %s : %d comptes de copropriétaires renseignés. Complétez-la "
                                "(solde bancaire, factures à payer, autres soldes) puis comptabilisez-la."
                                % (self.date_reprise.strftime("%d/%m/%Y"), len(plan["soldes"])))
        if avertissements:
            compte_rendu.append("")
            compte_rendu.append("À vérifier :")
            compte_rendu.extend("   – %s" % a for a in avertissements)
        texte = "\n".join(compte_rendu) or "Rien à importer."
        self.write({"etat": "importe", "journal": texte, "rapport": rapport, "nombre_anomalies": 0})
        self.message_post(body=texte.replace("\n", "<br/>"))
        return True

    def action_voir_reprise(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "coproerp.reprise", "res_id": self.reprise_id.id,
                "view_mode": "form"}

    def action_remettre_a_analyser(self):
        self.write({"etat": "brouillon", "rapport": False})
        return True

    # ------------------------------------------------------------------
    # Modèle vierge
    # ------------------------------------------------------------------
    def action_telecharger_modele(self):
        self.ensure_one()
        self.modele = base64.b64encode(modele_classeur())
        return {
            "type": "ir.actions.act_url", "target": "self",
            "url": "/web/content/coproerp.import.excel/%d/modele/modele_import_copropriete.xlsx?download=true"
                   % self.id,
        }


def _euros(montant):
    return "{:,.2f} €".format(montant).replace(",", " ").replace(".", ",")


def modele_classeur():
    """Classeur vierge, avec une ligne d'exemple par feuille."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    classeur = openpyxl.Workbook()
    feuilles = [
        ("Lots", ["N° de lot", "Bâtiment", "Escalier", "Désignation", "Usage", "Nature", "Étage", "Surface (m²)"],
         [["1", "A", "1", "Appartement 3 pièces", "Appartement", "Principal", "2", 68.5],
          ["101", "A", "", "Cave n° 1", "Cave", "Secondaire", "Sous-sol", ""]]),
        ("Copropriétaires", ["N° de compte", "Nom", "Prénom", "Adresse", "Complément d'adresse", "Code postal",
                             "Ville", "E-mail", "Téléphone", "Lots", "Type de droit", "Quote-part (%)",
                             "Date d'entrée", "Mandataire commun"],
         [["61651/1", "DUPONT", "Marie", "12 rue des Lilas", "", "75008", "Paris", "marie.dupont@exemple.fr",
           "06 00 00 00 00", "1, 101", "Propriétaire", 100, "15/03/2012", ""]]),
        ("Tantièmes", ["N° de lot", "Charges générales", "Ascenseur", "Chauffage"],
         [["1", 120, 150, 130], ["101", 5, "", ""]]),
        ("Soldes", ["N° de compte", "Nom du copropriétaire", "Solde", "Fonds de travaux", "Avance"],
         [["61651/1", "DUPONT Marie", -350.25, 840.0, 150.0]]),
    ]
    entete = PatternFill("solid", fgColor="1F4E78")
    for index, (titre, colonnes, exemples) in enumerate(feuilles):
        feuille = classeur.active if index == 0 else classeur.create_sheet()
        feuille.title = titre
        feuille.append(colonnes)
        for cellule in feuille[1]:
            cellule.font = Font(bold=True, color="FFFFFF")
            cellule.fill = entete
        for exemple in exemples:
            feuille.append(exemple)
        for position, nom in enumerate(colonnes, start=1):
            feuille.column_dimensions[openpyxl.utils.get_column_letter(position)].width = max(14, len(nom) + 4)
    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()
