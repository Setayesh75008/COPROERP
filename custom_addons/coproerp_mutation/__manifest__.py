{
    "name": "CoproERP - Mutations (vente d'un lot) et état daté",
    "summary": "Pré-état daté, état daté (art. 5 du décret de 1967), certificat de l'art. 20, transfert du lot",
    "description": """
Vente d'un lot de copropriété :

- dossier de mutation : lots, vendeur, acquéreur, notaire, dates ;
- pré-état daté (informations financières remises avant la promesse de vente,
  art. L. 721-2 du code de la construction et de l'habitation) ;
- état daté (art. 5 du décret du 17 mars 1967) en trois parties : sommes dues
  par le vendeur, sommes dues au vendeur, sommes à la charge de l'acquéreur ;
  calcul automatique à partir de la comptabilité, des budgets et des
  échéanciers de travaux ; chiffres figés à l'émission ;
- honoraires d'état daté imputés au seul vendeur (art. 10-1 de la loi),
  plafonnés à 380 € TTC ;
- certificat de l'article 20 de la loi (vendeur libre de toute obligation) ;
- réalisation de la vente : changement de propriétaire du lot, transfert de la
  quote-part du fonds de travaux attachée au lot (et, au choix, de l'avance de
  trésorerie) au profit de l'acquéreur.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "depends": [
        "coproerp_recouvrement",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/mutation_views.xml",
        "report/mutation_report.xml",
        "report/mutation_templates.xml",
    ],
    "installable": True,
    "application": False,
}
