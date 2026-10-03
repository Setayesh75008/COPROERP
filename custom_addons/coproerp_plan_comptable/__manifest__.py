{
    "name": "CoproERP - Plan comptable des copropriétés",
    "summary": "Plan comptable des syndicats de copropriétaires (décret n° 2005-240)",
    "description": """
Plan comptable des syndicats de copropriétaires, chargé dans le dossier
comptable de chaque copropriété (une « société » Odoo par syndicat).

Les comptes sont définis dans data/template/account.account-copro_fr.csv :
pour ajouter ou renuméroter un compte, modifiez ce fichier (6 chiffres).
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    # Catégorie obligatoire pour qu'Odoo reconnaisse un plan comptable
    "category": "Accounting/Localizations/Account Charts",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [],
    "installable": True,
    "application": False,
}
