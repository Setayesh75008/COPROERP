{
    "name": "CoproERP - Extranet copropriétaires",
    "summary": "Espace en ligne sécurisé des copropriétaires et du conseil syndical",
    "description": """
Extranet des copropriétaires (espace en ligne sécurisé, art. 18 de la loi
du 10 juillet 1965, décret n° 2019-502 du 23 mai 2019).

Accès : propriétaires, usufruitiers, nus-propriétaires et indivisaires dont la
fiche Droit est en cours. Les locataires n'y ont pas accès. Les membres du
conseil syndical ont en plus accès, pendant leur mandat, aux comptes de tous
les copropriétaires de l'immeuble et aux documents réservés.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.2",
    "license": "LGPL-3",
    "depends": [
        "portal",
        "mail",
        "coproerp_copropriete",
        "coproerp_batiment",
        "coproerp_lot",
        "coproerp_droit",
        "coproerp_personne",
        "coproerp_navigation",
        "coproerp_appel_charge",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/extranet_security.xml",
        "data/document_categorie_data.xml",
        "data/cron_data.xml",
        "views/copropriete_views.xml",
        "views/cs_mandat_views.xml",
        "views/document_views.xml",
        "views/actualite_views.xml",
        "views/dematerialisation_views.xml",
        "views/rib_demande_views.xml",
        "views/res_partner_views.xml",
        "views/extranet_menus.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "coproerp_extranet/static/src/scss/extranet.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
