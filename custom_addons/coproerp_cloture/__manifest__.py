{
    "name": "CoproERP - Clôture de l'exercice et annexes comptables",
    "summary": "Contrôles de clôture, verrouillage de l'exercice et les 5 annexes du décret n° 2005-240",
    "description": """
Clôture de l'exercice du syndicat des copropriétaires :

- contrôles préalables (appels comptabilisés, factures validées, régularisation
  des charges comptabilisée, fonds de travaux mis en réserve, équilibre) ;
- verrouillage des écritures de l'exercice clos ;
- les cinq annexes comptables jointes à la convocation de l'assemblée
  (décret n° 2005-240 du 14 mars 2005, arrêté du 14 mars 2005) :
  1. état financier après répartition ;
  2. compte de gestion général et budget prévisionnel ;
  3. compte de gestion pour opérations courantes ;
  4. compte de gestion pour travaux de l'art. 14-2 et opérations exceptionnelles ;
  5. état des travaux et opérations exceptionnelles votés non encore clôturés.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.2",
    "license": "LGPL-3",
    "depends": [
        "coproerp_regularisation",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/cloture_views.xml",
        "report/annexes_report.xml",
        "report/annexes_templates.xml",
    ],
    "installable": True,
    "application": False,
}
