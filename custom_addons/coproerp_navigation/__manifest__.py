{
    "name": "CoproERP - Navigation",
    "version": "19.0.1.0.0",
    "author": "SSB AVOCAT",
    "license": "LGPL-3",

    "depends": [
    "coproerp_copropriete",
    "coproerp_batiment",
    "coproerp_lot",
    "coproerp_personne",
    "coproerp_droit",
    "coproerp_repartition",
    ],

    "data": [
        "views/copropriete_navigation_views.xml",
        "views/batiment_navigation_views.xml",
        "views/lot_navigation_views.xml",
        "views/personne_navigation_views.xml",
        "views/droit_navigation_views.xml",
    ],

    "installable": True,
    "application": False,
}
