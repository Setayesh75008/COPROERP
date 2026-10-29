{
    "name": "CoproERP - Gestion courante",
    "summary": "Rapprochement bancaire, sinistres, avoirs et paiements groupés, intérêts au taux légal",
    "description": """
Outils de gestion courante du syndic :

- rapprochement bancaire : import du relevé (CSV ou OFX), pointage automatique
  avec les écritures, création des règlements de copropriétaires et des
  paiements de fournisseurs manquants, état de rapprochement ;
- sinistres : déclaration à l'assureur dans les délais (code des assurances),
  suivi de l'expertise et de l'indemnisation, encaissement de l'indemnité ;
- avoirs fournisseurs et paiement de plusieurs factures en une seule fois ;
- intérêts au taux légal dus à compter de la mise en demeure (art. 36 du
  décret du 17 mars 1967), table des taux semestriels.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_carnet_entretien",
        "coproerp_recouvrement",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/taux_legal_data.xml",
        "data/sequence.xml",
        "views/taux_legal_views.xml",
        "views/interets_views.xml",
        "views/avoir_views.xml",
        "views/sinistre_views.xml",
        "views/rapprochement_views.xml",
        "report/reports.xml",
        "report/sinistre_templates.xml",
        "report/rapprochement_templates.xml",
    ],
    "installable": True,
    "application": False,
}
