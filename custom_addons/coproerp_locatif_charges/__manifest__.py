{
    "name": "CoproERP - Gestion locative : révision des loyers et régularisation des charges",
    "summary": "Indices IRL, ILC, ILAT, révision annuelle des loyers, régularisation annuelle des charges récupérables",
    "description": """
Étape 2 de la gestion locative :

- table des indices publiés par l'INSEE (IRL, ILC, ILAT, ICC), à compléter
  chaque trimestre ;
- révision annuelle du loyer à la date prévue au bail : nouveau loyer =
  loyer × nouvel indice ÷ indice de référence du même trimestre ; pour un
  logement, révision sans effet rétroactif et perdue après un an
  (art. 17-1 de la loi du 6 juillet 1989) ; lettre au locataire ;
- régularisation annuelle des charges récupérables (art. 23 de la loi de
  1989, décret n° 87-713) : provisions appelées comparées aux charges réelles
  par nature, reprises au besoin des factures de la copropriété quand le bien
  est un lot géré dans CoproERP ; décompte au locataire, complément ou
  remboursement porté à son compte, nouvelle provision mensuelle.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_locatif",
        "coproerp_depenses",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/indices_data.xml",
        "data/cron.xml",
        "views/indice_views.xml",
        "views/revision_views.xml",
        "views/regularisation_views.xml",
        "views/bail_views.xml",
        "views/menus.xml",
        "report/reports.xml",
        "report/revision_templates.xml",
        "report/regularisation_templates.xml",
    ],
    "installable": True,
    "application": False,
}
