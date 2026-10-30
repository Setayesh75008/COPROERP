"""Lecture d'un classeur Excel d'ancien syndic, sans dépendance à Odoo (testable seule).

Chaque feuille est reconnue par sa ligne d'en-tête, quel que soit son nom :
lots, copropriétaires, tantièmes (une colonne par clé) ou soldes.
"""

import io
import re
import unicodedata
from datetime import date, datetime

LIGNES_ENTETE_MAX = 10


def normaliser(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", texte.upper()).split())


def texte_cellule(valeur):
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    if isinstance(valeur, datetime):
        return valeur.strftime("%d/%m/%Y")
    return str(valeur).strip()


def nombre_cellule(valeur):
    """Nombre d'une cellule (« 1 234,56 », « -12.5 », « 1 200 € »…) ; None si vide."""
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).strip().replace(" ", "").replace(" ", "").replace(" ", "")
    texte = texte.replace("€", "").replace("EUR", "")
    if not texte:
        return None
    if "," in texte and "." in texte:
        texte = texte.replace(".", "").replace(",", ".") if texte.rfind(",") > texte.rfind(".") \
            else texte.replace(",", "")
    else:
        texte = texte.replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        raise ValueError("« %s » n'est pas un nombre" % valeur) from None


def date_cellule(valeur):
    if valeur in (None, ""):
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = str(valeur).strip()
    for format_date in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(texte[:10], format_date).date()
        except ValueError:
            continue
    raise ValueError("« %s » n'est pas une date (format attendu : JJ/MM/AAAA)" % valeur)


def liste_lots(valeur):
    """« 1, 12 et 15 » → ['1', '12', '15']."""
    texte = texte_cellule(valeur)
    morceaux = re.split(r"[,;+]|\s+et\s+|\s+", texte, flags=re.I)
    return [m.strip() for m in morceaux if m.strip()]


# ----------------------------------------------------------------------
# Reconnaissance des colonnes
# ----------------------------------------------------------------------
def _mots(nom):
    return nom.split()


COLONNES = {
    "lots": [
        ("tantiemes", lambda n: "TANTIEME" in n or "TANTIEMES" in n or n.startswith("MILLIEME")),
        ("designation", lambda n: n.startswith(("DESIGNATION", "DESCRIPTION", "LIBELLE"))),
        ("numero", lambda n: "LOT" in _mots(n) or n.startswith("NUMERO") or n in ("N", "NO")),
        ("batiment", lambda n: n.startswith(("BATIMENT", "BAT", "IMMEUBLE"))),
        ("escalier", lambda n: n.startswith(("ESCALIER", "ESC", "ENTREE"))),
        ("nature", lambda n: n.startswith("NATURE")),
        ("usage", lambda n: n.startswith(("USAGE", "TYPE"))),
        ("etage", lambda n: n.startswith(("ETAGE", "NIVEAU"))),
        ("surface", lambda n: n.startswith("SURFACE")),
    ],
    "coproprietaires": [
        ("code_postal", lambda n: n.startswith(("CODE POSTAL", "CP")) or n == "CP"),
        ("email", lambda n: "MAIL" in n or n.startswith("COURRIEL")),
        ("telephone", lambda n: n.startswith(("TEL", "PORTABLE", "MOBILE"))),
        ("compte", lambda n: n.startswith(("N DE COMPTE", "N COMPTE", "COMPTE", "N DE CONTRAT", "CONTRAT",
                                           "CODE", "REFERENCE", "REF"))),
        ("prenom", lambda n: n.startswith("PRENOM")),
        ("mandataire", lambda n: n.startswith("MANDATAIRE")),
        ("nom", lambda n: n.startswith(("NOM", "RAISON SOCIALE", "COPROPRIETAIRE", "DENOMINATION"))),
        ("adresse2", lambda n: n.startswith(("COMPLEMENT", "ADRESSE 2", "ADRESSE2"))),
        ("adresse", lambda n: n.startswith("ADRESSE")),
        ("ville", lambda n: n.startswith(("VILLE", "COMMUNE", "LOCALITE"))),
        ("quotite", lambda n: n.startswith(("QUOTITE", "QUOTE"))),
        ("droit", lambda n: n.startswith(("TYPE DE DROIT", "DROIT", "QUALITE"))),
        ("date", lambda n: n.startswith("DATE")),
        ("lots", lambda n: "LOT" in n),
    ],
    "soldes": [
        ("solde", lambda n: n.startswith("SOLDE")),
        ("fonds_travaux", lambda n: n.startswith("FONDS")),
        ("avance", lambda n: n.startswith("AVANCE") or "ROULEMENT" in n),
        ("compte", lambda n: n.startswith(("N DE COMPTE", "N COMPTE", "COMPTE", "N DE CONTRAT", "CONTRAT",
                                           "CODE", "REFERENCE", "REF"))),
        ("nom", lambda n: n.startswith(("NOM", "COPROPRIETAIRE", "RAISON SOCIALE"))),
    ],
}


def _attribuer(noms, specification):
    colonnes, prises = {}, set()
    for champ, test in specification:
        for position, nom in enumerate(noms):
            if position not in prises and nom and test(nom):
                colonnes[champ] = position
                prises.add(position)
                break
    return colonnes


def _type_feuille(titre, noms):
    titre = normaliser(titre)
    if any(n.startswith("SOLDE") for n in noms) and any(
            n.startswith(("NOM", "COMPTE", "N DE", "N COMPTE", "CONTRAT", "COPROPRIETAIRE")) for n in noms):
        return "soldes"
    a_lot = any("LOT" in n for n in noms)
    if a_lot and any(n.startswith(("NOM", "RAISON SOCIALE", "COPROPRIETAIRE", "DENOMINATION")) for n in noms):
        return "coproprietaires"
    if "TANTIEM" in titre or "MILLIEM" in titre or "CLE" in titre.split():
        return "tantiemes" if a_lot else None
    if a_lot and any(n.startswith(("DESIGNATION", "DESCRIPTION", "LIBELLE", "USAGE", "BATIMENT", "ETAGE",
                                   "SURFACE", "NATURE", "TYPE")) for n in noms):
        return "lots"
    if a_lot and len([n for n in noms if n]) >= 2:
        return "tantiemes"
    return None


def lire_classeur(contenu):
    """Retourne (donnees, anomalies).

    donnees = {"lots": [...], "coproprietaires": [...], "soldes": [...],
               "tantiemes": {"cles": [noms], "lignes": [{"ligne", "numero", "valeurs": {cle: int}}]},
               "colonnes_soldes": set(champs présents)}
    anomalies = [(feuille, ligne, message)]
    """
    import openpyxl  # dépendance d'Odoo (import de fichiers)

    try:
        classeur = openpyxl.load_workbook(io.BytesIO(contenu), data_only=True, read_only=True)
    except Exception as erreur:  # fichier .xls, .csv, corrompu…
        raise ValueError("Le fichier n'est pas un classeur Excel .xlsx lisible (%s). Si c'est un ancien "
                         "fichier .xls, enregistrez-le au format .xlsx." % erreur) from None
    donnees = {"lots": [], "coproprietaires": [], "soldes": [], "tantiemes": {"cles": [], "lignes": []},
               "colonnes_soldes": set(), "feuilles": []}
    anomalies = []
    for feuille in classeur.worksheets:
        lignes = list(feuille.iter_rows(values_only=True))
        entete, nature = None, None
        for index, ligne in enumerate(lignes[:LIGNES_ENTETE_MAX]):
            noms = [normaliser(c) for c in ligne]
            nature = _type_feuille(feuille.title, noms)
            if nature:
                entete = index
                break
        if nature is None:
            anomalies.append((feuille.title, 0, "Feuille ignorée : en-têtes non reconnus."))
            continue
        donnees["feuilles"].append((feuille.title, nature))
        noms = [normaliser(c) for c in lignes[entete]]
        libelles = [texte_cellule(c) for c in lignes[entete]]
        if nature == "tantiemes":
            colonne_lot = next(i for i, n in enumerate(noms) if "LOT" in n)
            cles = [(i, libelles[i]) for i, n in enumerate(noms)
                    if i != colonne_lot and n and not n.startswith(("DESIGNATION", "NOM", "TOTAL", "BATIMENT"))]
            for _i, cle in cles:
                if cle not in donnees["tantiemes"]["cles"]:
                    donnees["tantiemes"]["cles"].append(cle)
            for numero_ligne, ligne in enumerate(lignes[entete + 1:], start=entete + 2):
                numero = texte_cellule(ligne[colonne_lot]) if colonne_lot < len(ligne) else ""
                if not numero or normaliser(numero).startswith("TOTAL"):
                    continue
                valeurs = {}
                for position, cle in cles:
                    cellule = ligne[position] if position < len(ligne) else None
                    try:
                        valeur = nombre_cellule(cellule)
                    except ValueError as erreur:
                        anomalies.append((feuille.title, numero_ligne, "Lot %s, clé %s : %s." % (numero, cle, erreur)))
                        continue
                    if valeur is None:
                        continue
                    if valeur < 0 or not float(valeur).is_integer():
                        anomalies.append((feuille.title, numero_ligne, "Lot %s, clé %s : les tantièmes doivent être "
                                          "des nombres entiers positifs (%s)." % (numero, cle, cellule)))
                        continue
                    valeurs[cle] = int(valeur)
                donnees["tantiemes"]["lignes"].append({"ligne": numero_ligne, "numero": numero, "valeurs": valeurs})
            continue

        colonnes = _attribuer(noms, COLONNES[nature])
        obligatoires = {"lots": ["numero"], "coproprietaires": ["nom", "lots"], "soldes": ["solde"]}[nature]
        manquantes = [c for c in obligatoires if c not in colonnes]
        if nature == "soldes" and "compte" not in colonnes and "nom" not in colonnes:
            manquantes.append("compte ou nom")
        if manquantes:
            anomalies.append((feuille.title, entete + 1, "Colonne(s) introuvable(s) : %s." % ", ".join(manquantes)))
            continue
        if nature == "soldes":
            donnees["colonnes_soldes"] |= set(colonnes)
        cle_lots = libelles[colonnes["tantiemes"]] if nature == "lots" and "tantiemes" in colonnes else None
        if cle_lots and "Charges générales" not in donnees["tantiemes"]["cles"]:
            donnees["tantiemes"]["cles"].insert(0, "Charges générales")
        for numero_ligne, ligne in enumerate(lignes[entete + 1:], start=entete + 2):
            def valeur(champ):
                position = colonnes.get(champ)
                return ligne[position] if position is not None and position < len(ligne) else None

            if not any(texte_cellule(c) for c in ligne):
                continue
            try:
                if nature == "lots":
                    numero = texte_cellule(valeur("numero"))
                    if not numero or normaliser(numero).startswith("TOTAL"):
                        continue
                    surface = nombre_cellule(valeur("surface"))
                    donnees["lots"].append({
                        "ligne": numero_ligne, "numero": numero,
                        "designation": texte_cellule(valeur("designation")),
                        "batiment": texte_cellule(valeur("batiment")),
                        "escalier": texte_cellule(valeur("escalier")),
                        "usage": texte_cellule(valeur("usage")),
                        "nature": texte_cellule(valeur("nature")),
                        "etage": texte_cellule(valeur("etage")),
                        "surface": surface or 0.0,
                    })
                    if cle_lots:
                        tantiemes = nombre_cellule(valeur("tantiemes"))
                        if tantiemes is not None:
                            if tantiemes < 0 or not float(tantiemes).is_integer():
                                raise ValueError("tantièmes non entiers ou négatifs (%s)" % tantiemes)
                            donnees["tantiemes"]["lignes"].append({
                                "ligne": numero_ligne, "numero": numero,
                                "valeurs": {"Charges générales": int(tantiemes)}})
                elif nature == "coproprietaires":
                    nom = texte_cellule(valeur("nom"))
                    if not nom or normaliser(nom).startswith("TOTAL"):
                        continue
                    prenom = texte_cellule(valeur("prenom"))
                    quotite = nombre_cellule(valeur("quotite"))
                    donnees["coproprietaires"].append({
                        "ligne": numero_ligne, "compte": texte_cellule(valeur("compte")),
                        "nom": " ".join(x for x in (nom, prenom) if x),
                        "adresse": texte_cellule(valeur("adresse")), "adresse2": texte_cellule(valeur("adresse2")),
                        "code_postal": texte_cellule(valeur("code_postal")), "ville": texte_cellule(valeur("ville")),
                        "email": texte_cellule(valeur("email")), "telephone": texte_cellule(valeur("telephone")),
                        "lots": liste_lots(valeur("lots")), "droit": texte_cellule(valeur("droit")),
                        "quotite": quotite if quotite is not None else 100.0,
                        "date": date_cellule(valeur("date")),
                        "mandataire": normaliser(texte_cellule(valeur("mandataire"))) in ("OUI", "O", "X", "1", "VRAI"),
                    })
                else:
                    nom = texte_cellule(valeur("nom"))
                    compte = texte_cellule(valeur("compte"))
                    if not (nom or compte) or normaliser(nom or compte).startswith("TOTAL"):
                        continue
                    donnees["soldes"].append({
                        "ligne": numero_ligne, "compte": compte, "nom": nom,
                        "solde": nombre_cellule(valeur("solde")) or 0.0,
                        "fonds_travaux": nombre_cellule(valeur("fonds_travaux")) or 0.0,
                        "avance": nombre_cellule(valeur("avance")) or 0.0,
                    })
            except ValueError as erreur:
                anomalies.append((feuille.title, numero_ligne, str(erreur)))
    return donnees, anomalies


# ----------------------------------------------------------------------
# Traduction des valeurs libres
# ----------------------------------------------------------------------
def usage_lot(texte):
    n = normaliser(texte)
    for prefixes, usage in (
        (("APPART", "APPT", "STUDIO", "LOGEMENT", "DUPLEX", "T1", "T2", "T3", "T4", "T5", "F1", "F2", "F3", "F4",
          "F5", "MAISON", "PAVILLON", "CHAMBRE"), "appartement"),
        (("PARKING", "GARAGE", "BOX", "STATIONNEMENT", "EMPLACEMENT"), "parking"),
        (("CAVE",), "cave"),
        (("LOCAL COMMERCIAL", "COMMERCE", "BOUTIQUE", "MAGASIN", "LOCAL"), "local"),
        (("BUREAU",), "bureau"),
        (("CELLIER", "GRENIER", "DEBARRAS"), "cellier"),
        (("JARDIN", "TERRASSE", "COUR"), "jardin"),
    ):
        if n.startswith(prefixes):
            return usage
    return "autre" if n else "appartement"


def nature_lot(texte, usage):
    n = normaliser(texte)
    if n.startswith("SECOND") or n.startswith("ANNEXE"):
        return "secondaire"
    if n.startswith("PRINC"):
        return "principal"
    return "secondaire" if usage in ("parking", "cave", "cellier", "jardin") else "principal"


def type_droit(texte):
    n = normaliser(texte)
    if not n or n.startswith(("PROPRIETAIRE", "PLEINE", "COPROPRIETAIRE")):
        return "proprietaire"
    if n.startswith("USUFRUIT"):
        return "usufruitier"
    if n.startswith(("NU", "NUE")):
        return "nu_proprietaire"
    if n.startswith("INDIVIS"):
        return "indivisaire"
    if n.startswith(("LOCATAIRE", "OCCUPANT")):
        return "locataire"
    return None


def type_cle(nom):
    n = normaliser(nom)
    if "ASCENSEUR" in n or "ESCALIER" in n:
        return "ascenseur_escalier"
    if "CHAUFFAGE" in n:
        return "chauffage"
    if "EAU" in n.split() and "CHAUDE" in n:
        return "eau_chaude"
    if "FONDS" in n:
        return "fonds_travaux"
    if "GENERAL" in n or "COMMUNES" in n:
        return "charges_generales"
    return "autre"
