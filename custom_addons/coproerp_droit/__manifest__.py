{
    "name": "CoproERP - Droits",
    "version": "19.0.1.0.0",
    "author": "SSB AVOCAT",
    "website": "",
    "license": "LGPL-3",

    "depends": [
        "base",
        "coproerp_lot",
    ],
    
    "data": [
        "security/ir.model.access.csv",
        "data/droit_sequence.xml",
        "views/droit_views.xml",
        "views/droit_menus.xml",
    ],

    "installable": True,
    "application": False,
}