{
    "name": "CoproERP - Appels de fonds",
    "version": "19.0.1.0.0",
    "author": "SSB AVOCAT",
    "license": "LGPL-3",

    "depends": [
        "base",
        "coproerp_copropriete",
        "coproerp_lot",
        "coproerp_personne",
        "coproerp_droit",
        "coproerp_repartition",
        "coproerp_budget",
        "coproerp_travaux",
    ],

    "data": [
        "security/ir.model.access.csv",
        "data/appel_charge_sequence.xml",
        "views/appel_charge_views.xml",
        "views/appel_charge_menus.xml",
    ],

    "installable": True,
    "application": False,
}