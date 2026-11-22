{
    "name": "CoproERP - Gestion locative : comptes des propriétaires et reversements",
    "summary": "Honoraires de gestion, factures payées pour le compte des propriétaires, comptes rendus de gestion, "
               "virements aux propriétaires, récapitulatif annuel des revenus fonciers",
    "description": """
Étape 3 de la gestion locative :

- honoraires de gestion prélevés sur les sommes encaissées (taux du mandat,
  dépôts de garantie exclus) ;
- factures payées pour le compte d'un propriétaire (charges de copropriété,
  travaux, assurance, taxe foncière…), dans la limite de ses fonds ;
- compte rendu de gestion mensuel ou trimestriel : relevé du compte du
  propriétaire, situation des locataires, somme disponible ;
- virements aux propriétaires, limités à la somme réellement encaissée et
  disponible ; virement des honoraires au cabinet ;
- récapitulatif annuel pour la déclaration des revenus fonciers.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "depends": [
        "coproerp_locatif",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/depense_views.xml",
        "views/compte_rendu_views.xml",
        "views/reversement_views.xml",
        "views/mandat_views.xml",
        "wizard/preparation_views.xml",
        "wizard/recap_views.xml",
        "views/menus.xml",
        "report/reports.xml",
        "report/compte_rendu_templates.xml",
        "report/recap_templates.xml",
    ],
    "installable": True,
    "application": False,
}
