{
    "name": "CoproERP - Reprise des soldes (démarrage d'une copropriété)",
    "summary": "Soldes d'ouverture : banque, comptes des copropriétaires, fonds de travaux, avances, factures en attente",
    "description": """
Reprise d'une copropriété gérée jusque-là par un autre syndic ou un autre logiciel :

- saisie, à la date de reprise, du solde bancaire, du solde de chaque
  copropriétaire (débiteur ou créditeur), de son fonds de travaux cumulé et de
  son avance de trésorerie (fonds de roulement) ;
- factures fournisseurs restant à payer : elles deviennent des factures
  CoproERP payables par le circuit habituel ;
- autres soldes (provisions, travaux en attente, comptes de tiers…) ;
- contrôle d'équilibre puis écriture d'à-nouveaux au journal des opérations
  diverses ; les soldes apparaissent ensuite sur les relevés, les avis
  d'appel, l'extranet et les relances.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.3",
    "license": "LGPL-3",
    "depends": [
        "coproerp_depenses",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/reprise_views.xml",
    ],
    "installable": True,
    "application": False,
}
