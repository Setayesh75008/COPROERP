{
    "name": "CoproERP - Carnet d'entretien de l'immeuble",
    "summary": "Carnet d'entretien (art. 18 de la loi de 1965, décret n° 2001-477) : assurances, contrats, travaux, diagnostics",
    "description": """
Carnet d'entretien de l'immeuble tenu par le syndic (art. 18 de la loi du
10 juillet 1965, décret n° 2001-477 du 30 mai 2001) :

- contrats d'assurance de l'immeuble et assurances dommages-ouvrage ;
- contrats d'entretien et de maintenance des équipements communs, avec leurs
  échéances et un suivi des contrats à renouveler ou à résilier ;
- travaux importants réalisés (ravalement, toiture, ascenseur, chauffage,
  canalisations…), année et entreprise, repris des opérations de travaux ;
- échéancier des travaux votés par l'assemblée (plan pluriannuel) ;
- diagnostics techniques (amiante, plomb, DPE, DTG, audit énergétique…) ;
- PDF du carnet et mise à disposition sur l'extranet.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_fiche_synthetique",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/carnet_views.xml",
        "report/carnet_report.xml",
        "report/carnet_templates.xml",
    ],
    "installable": True,
    "application": False,
}
