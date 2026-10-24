{
    "name": "CoproERP - Régularisation annuelle des charges",
    "summary": "Dépenses réelles moins provisions appelées, par lot et par clé ; décomptes individuels",
    "description": """
Régularisation des charges de l'exercice :

- pour chaque lot et chaque clé de répartition : quote-part des dépenses
  réelles de l'exercice (hors travaux de l'article 14-2) moins provisions
  appelées sur le budget prévisionnel ;
- solde porté au compte du copropriétaire à la date retenue (en principe celle
  de l'approbation des comptes, art. 6-2 du décret du 17 mars 1967) ;
- écriture au journal des opérations diverses (450 / 701), lettrée avec les
  sommes dues ou versées d'avance ;
- décompte individuel de charges (PDF) ;
- relevé général des dépenses de l'exercice par clé et par nature, avec la TVA
  et l'indication des charges récupérables sur le locataire (PDF).
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.5",
    "license": "LGPL-3",
    "depends": [
        "coproerp_depenses",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/regularisation_views.xml",
        "views/budget_views.xml",
        "report/decompte_report.xml",
        "report/decompte_templates.xml",
        "report/releve_depenses_report.xml",
        "report/releve_depenses_templates.xml",
    ],
    "installable": True,
    "application": False,
}
