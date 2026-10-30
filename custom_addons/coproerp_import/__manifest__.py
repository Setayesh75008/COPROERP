{
    "name": "CoproERP - Import Excel (lots, copropriétaires, tantièmes, soldes)",
    "summary": "Reprise d'une copropriété depuis les tableaux Excel de l'ancien syndic",
    "description": """
Import, dans une copropriété existante, d'un classeur Excel contenant tout ou
partie des feuilles suivantes (reconnues par leurs en-têtes) :

- Lots : numéro, bâtiment, désignation, usage, nature, étage, surface ;
- Copropriétaires : n° de compte, nom, adresse, e-mail, téléphone, lots
  détenus, type de droit, date d'entrée, mandataire commun ;
- Tantièmes : une colonne par clé de répartition ;
- Soldes : n° de compte, nom, solde (format des exports d'ancien syndic),
  fonds de travaux et avance facultatifs : ils alimentent la reprise des soldes.

Le fichier est d'abord analysé (aucune donnée créée, liste des anomalies),
puis importé. Un nouvel import du même fichier met à jour sans doublon.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_reprise",
    ],
    "external_dependencies": {"python": ["openpyxl"]},
    "data": [
        "security/ir.model.access.csv",
        "views/import_views.xml",
    ],
    "installable": True,
    "application": False,
}
