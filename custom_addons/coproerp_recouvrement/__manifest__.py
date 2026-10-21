{
    "name": "CoproERP - Recouvrement des charges",
    "summary": "Relances, mises en demeure (art. 19-2 et 10-1 de la loi de 1965), suivi des impayés",
    "description": """
Recouvrement des sommes dues par les copropriétaires :

- préparation des relances : liste des débiteurs, retard, dernière relance,
  proposition (relance simple puis mise en demeure) ;
- lettre de relance (sans frais) avec relevé de compte et papillon ;
- mise en demeure par lettre recommandée (électronique par défaut, art. 42-1),
  mentions des art. 36 du décret de 1967 (intérêts au taux légal), 19-2
  (exigibilité anticipée après 30 jours) et 10-1 (frais imputables) ;
- frais de mise en demeure imputés au seul copropriétaire défaillant
  (450 / 714), venant en déduction des charges lors de la régularisation ;
- suivi : n° de recommandé, date de première présentation, échéance du délai
  de 30 jours, compte soldé ou non.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "depends": [
        "coproerp_regularisation",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/relance_views.xml",
        "views/copropriete_views.xml",
        "wizard/preparation_views.xml",
        "report/relance_report.xml",
        "report/relance_templates.xml",
    ],
    "installable": True,
    "application": False,
}
