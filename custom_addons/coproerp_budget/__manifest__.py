{
    "name": "CoproERP - Budget et Fonds de travaux",
    "version": "1.0",
    "author": "SSB AVOCAT",
    "category": "Copropriété",
    "license": "LGPL-3",
    "depends": [
        "base",
        "coproerp_copropriete",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/budget_sequence.xml",
        "views/budget_views.xml",
        "views/budget_menus.xml",
    ],
    "installable": True,
    "application": False,
}