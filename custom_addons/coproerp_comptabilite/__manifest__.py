{
    "name": "CoproERP - Comptabilité des copropriétés",
    "summary": "Dossier comptable par syndicat, écritures des appels, règlements, relevé de compte",
    "description": """
Comptabilité en partie double de chaque syndicat de copropriétaires :

- un dossier comptable (société Odoo) par copropriété, avec le plan comptable
  des syndicats, ses journaux (APF, BQ, ACH, OD) scellés (inaltérabilité) ;
- comptabilisation des appels de fonds (budget 450010/701, fonds travaux
  450050/705, travaux 450020/702, avances 450030/103) ;
- saisie des règlements des copropriétaires, imputés sur les appels les plus
  anciens et lettrés automatiquement ; annulation par contre-passation ;
- relevé de compte sur l'avis d'appel, solde réel sur l'extranet, relevé des
  dépenses pour le conseil syndical ;
- mise en réserve annuelle du fonds de travaux (705 -> 105).
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.5",
    "license": "LGPL-3",
    "depends": [
        "account",
        "coproerp_plan_comptable",
        "coproerp_appel_edition",
        "coproerp_extranet",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/copropriete_views.xml",
        "views/appel_views.xml",
        "views/reglement_views.xml",
        "wizard/mise_en_reserve_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
