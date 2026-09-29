{
    "name": "CoproERP - Lots",
    "version": "19.0.1.0.0",
    "author": "SSB AVOCAT",
    "website": "",
    "license": "LGPL-3",

    "depends": [
    "base",
    "coproerp_copropriete",
    "coproerp_batiment",
],

    "data": [
        "security/ir.model.access.csv",
        "views/lot_views.xml",
        "views/lot_menus.xml",
    ],

    "installable": True,
    "application": False,
}