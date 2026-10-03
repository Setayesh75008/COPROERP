{
    "name": "CoproERP - Dépenses (factures fournisseurs)",
    "summary": "Saisie des factures fournisseurs ventilées par clé de répartition, paiements, réalisé du budget",
    "description": """
Dépenses de la copropriété :

- factures fournisseurs saisies TTC (le syndicat ne récupère pas la TVA),
  chaque ligne portant une nature de dépense (compte 6xx) et une clé de
  répartition ;
- comptabilisation au journal des achats : débit 6xx / crédit 401 ;
- paiements au journal de banque : débit 401 / crédit 512, lettrés avec la facture ;
- travaux décidés par l'assemblée (art. 14-2) suivis hors budget ;
- réalisé et écart par clé sur le budget prévisionnel.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_comptabilite",
        "coproerp_travaux",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/natures_depense.xml",
        "views/nature_views.xml",
        "views/depense_views.xml",
        "views/paiement_views.xml",
        "views/budget_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
