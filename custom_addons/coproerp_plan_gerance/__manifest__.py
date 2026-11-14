{
    "name": "CoproERP - Plan comptable de la gestion locative (comptes des mandants)",
    "summary": "Plan comptable du dossier des fonds détenus pour le compte des propriétaires mandants",
    "description": """
Plan comptable du dossier « Fonds des mandants » de la gestion locative :
une seule banque pour tous les mandants, un sous-compte par propriétaire
(467100) et par locataire (411000), les dépôts de garantie détenus (165000)
et les fournisseurs payés pour le compte des propriétaires (401000).

Les comptes sont définis dans data/template/account.account-gerance_fr.csv.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    # Catégorie obligatoire pour qu'Odoo reconnaisse un plan comptable
    "category": "Accounting/Localizations/Account Charts",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["account", "coproerp_plan_comptable"],
    "data": [],
    "installable": True,
    "application": False,
}
