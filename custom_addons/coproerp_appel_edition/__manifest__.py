{
    "name": "CoproERP - Génération et édition des appels de fonds",
    "summary": "Budget par clé, génération trimestrielle, échéancier des travaux, avis d'appel PDF",
    "description": """
Génération et édition des appels de fonds :

- budget prévisionnel ventilé par clé de répartition ;
- génération des appels du budget courant et du fonds travaux par trimestre
  civil, exigibles le premier jour de chaque période (art. 14-1 loi 1965) ;
- destinataire déterminé par les fiches Droit ; en cas d'indivision ou de
  démembrement, l'appel est adressé au mandataire commun (art. 23 loi 1965) ;
- lots appartenant au syndicat exclus des appels ;
- échéancier des travaux en pourcentages, avec honoraires du syndic ;
- avis d'appel de fonds PDF (un avis par copropriétaire et par échéance) ;
- publication des avis sur l'extranet.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.2",
    "license": "LGPL-3",
    "depends": [
        "coproerp_lot",
        "coproerp_droit",
        "coproerp_repartition",
        "coproerp_budget",
        "coproerp_travaux",
        "coproerp_appel_charge",
        "coproerp_extranet",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/lot_views.xml",
        "views/budget_views.xml",
        "views/travaux_views.xml",
        "report/avis_appel_report.xml",
        "report/avis_appel_templates.xml",
        "views/appel_views.xml",
    ],
    "installable": True,
    "application": False,
}
