{
    "name": "CoproERP - Gestion locative : états des lieux et sortie du locataire",
    "summary": "États des lieux d'entrée et de sortie, congé, décompte de sortie, restitution du dépôt de garantie",
    "description": """
Étape 4 de la gestion locative :

- états des lieux d'entrée et de sortie, pièce par pièce, relevés des
  compteurs et clés remises ; l'état des lieux de sortie reprend celui
  d'entrée et signale les dégradations (art. 3-2 de la loi du 6 juillet 1989) ;
- congé du locataire et fin du préavis ;
- décompte de sortie : loyers et charges restant dus, retenues justifiées,
  provision de 20 % au plus en copropriété jusqu'à l'approbation des comptes ;
- restitution du dépôt de garantie dans le délai légal (un mois si l'état des
  lieux de sortie est conforme à celui d'entrée, deux mois sinon), majoration
  de 10 % du loyer par mois commencé en retard (art. 22) ; solde de tout compte.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_locatif",
        "coproerp_locatif_reversement",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/etat_lieux_views.xml",
        "views/sortie_views.xml",
        "views/bail_views.xml",
        "views/menus.xml",
        "report/reports.xml",
        "report/etat_lieux_templates.xml",
        "report/sortie_templates.xml",
    ],
    "installable": True,
    "application": False,
}
