{
    "name": "CoproERP - Répartition",
    "version": "19.0.1.0.0",
    "author": "SSB AVOCAT",
    "license": "LGPL-3",

    "depends": [
        "base",
        "coproerp_copropriete",
        "coproerp_lot",
    ],

    
    "data": [
    "security/ir.model.access.csv",
    "data/repartition_sequence.xml",
    "views/repartition_views.xml",
    "views/repartition_menus.xml",
    ],
    "installable": True,
    "application": False,
}