{
    "name": "CoproERP - Fiche synthétique de la copropriété",
    "summary": "Fiche synthétique (art. 8-2 de la loi de 1965, décret n° 2016-1822) : calcul, PDF, publication sur l'extranet",
    "description": """
Fiche synthétique de la copropriété, établie et mise à jour chaque année par
le syndic (art. 8-2 de la loi du 10 juillet 1965, décret n° 2016-1822 du
21 décembre 2016) :

- identification du syndicat et du syndic, organisation juridique ;
- caractéristiques techniques et équipements (lots par usage, bâtiments,
  période de construction, chauffage, ascenseurs) ;
- caractéristiques financières de l'exercice approuvé, reprises des comptes
  clôturés : charges courantes et de travaux, dettes, impayés, copropriétaires
  débiteurs de plus de 300 €, fonds de travaux ;
- PDF et mise à disposition des copropriétaires sur l'extranet.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_ag",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/fiche_views.xml",
        "report/fiche_report.xml",
        "report/fiche_templates.xml",
    ],
    "installable": True,
    "application": False,
}
