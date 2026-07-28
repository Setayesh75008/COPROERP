{
    'name': 'CoproERP Core',

    'summary': 'Noyau du logiciel CoproERP',

    'description': """
CoproERP Core
=============

Module de base du logiciel professionnel de gestion de copropriété.

Ce module contient :
- les paramètres généraux ;
- les groupes d'utilisateurs ;
- les menus principaux ;
- les fonctionnalités communes aux autres modules.
""",

    'author': 'SSB AVOCAT',
    'website': 'https://www.ssb-avocat.fr',

    'category': 'Real Estate',
    'version': '19.0.1.0.0',

    'license': 'LGPL-3',

    'depends': [
        'base',
        'mail',
        'contacts',
    ],

    'data': [],

    'demo': [],

    'application': True,
    'installable': True,
}
