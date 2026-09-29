{
    "name": "CoproERP - Travaux",
    "version": "19.0.1.0.0",
    "category": "Copropriété",
    "summary": "Gestion des travaux votés en copropriété",
    "description": """
Gestion des travaux votés en assemblée générale :
- projets de travaux ;
- décisions d'assemblée générale ;
- montants votés ;
- états d'avancement ;
- financements des travaux ;
- préparation des appels de fonds liés aux travaux.
""",
    "author": "SSB AVOCAT",
    "license": "LGPL-3",
    "depends": [
        "coproerp_copropriete",
        "coproerp_repartition",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/travaux_sequence.xml",
        "views/travaux_views.xml",
        "views/travaux_menus.xml",
    ],
    "installable": True,
    "application": False,
}
