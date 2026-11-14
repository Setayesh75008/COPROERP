{
    "name": "CoproERP - Gestion locative (baux, quittancement, encaissements)",
    "summary": "Mandats de gestion, biens, baux de tous types, avis d'échéance, quittances, encaissements et impayés",
    "description": """
Gestion locative pour le compte de propriétaires mandants, avec un compte
bancaire unique des mandants et un sous-compte par propriétaire et par
locataire (dossier comptable « Fonds des mandants »).

Étape 1 :

- dossier des mandants (société comptable dédiée, banque des mandants) ;
- registre des mandats de gestion, propriétaires, biens ;
- baux : habitation non meublée et meublée (loi du 6 juillet 1989), étudiant,
  mobilité, commercial, professionnel, stationnement, saisonnier, droit commun,
  avec leurs règles (durée, préavis, plafond du dépôt de garantie, indice) ;
- avis d'échéance (prorata du premier mois, terme échu ou à échoir, mensuel
  ou trimestriel, TVA pour les baux commerciaux), quittances (art. 21 de la loi
  de 1989), dépôt de garantie ;
- encaissements imputés sur les échéances les plus anciennes ;
- suivi des impayés, relances, mises en demeure et information de la caution.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "account",
        "coproerp_personne",
        "coproerp_plan_gerance",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/dossier_views.xml",
        "views/mandat_views.xml",
        "views/bien_views.xml",
        "views/bail_views.xml",
        "views/echeance_views.xml",
        "views/encaissement_views.xml",
        "views/relance_views.xml",
        "views/res_partner_views.xml",
        "wizard/quittancement_views.xml",
        "views/menus.xml",
        "report/reports.xml",
        "report/style.xml",
        "report/echeance_templates.xml",
        "report/relance_templates.xml",
    ],
    "installable": True,
    "application": True,
}
