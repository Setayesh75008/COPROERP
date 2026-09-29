{
    'name': 'CoproERP - Copropriétés',
    'summary': 'Gestion des copropriétés',
    'description': """
Module de gestion des copropriétés.

Ce module permet de gérer :
- les copropriétés,
- leurs informations administratives,
- leurs informations juridiques,
- leur organisation.
""",
    'author': 'SSB AVOCAT',
    'website': 'https://www.ssb-avocat.fr',
    'category': 'Real Estate',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',

    'depends': [
        'base',
        'coproerp_core',
    ],

    'data': [
    'security/ir.model.access.csv',
    'views/copropriete_views.xml',
    'views/copropriete_menus.xml',
],

    'installable': True,
    'application': True,
}