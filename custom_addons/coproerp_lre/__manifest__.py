{
    "name": "CoproERP - Lettre recommandée électronique (AR24)",
    "summary": "Envoi des mises en demeure, convocations d'AG et notifications de PV par LRE qualifiée AR24",
    "description": """
Notification par lettre recommandée électronique (art. 42-1 de la loi du
10 juillet 1965) au moyen du prestataire qualifié AR24 :

- compte AR24 du syndic (token, clé privée, expéditeur), plateforme de test ou
  de production, test de connexion ;
- envoi en un clic des mises en demeure, des convocations aux assemblées
  générales et des notifications du procès-verbal aux opposants et défaillants,
  pour les copropriétaires ayant accepté la voie électronique ;
- suivi automatique (toutes les heures) : dépôt, acceptation, refus,
  non-réclamation, adresse invalide ; la date de dépôt est reportée comme date
  de première présentation et le numéro AR24 comme numéro de recommandé.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "coproerp_ag",
        "coproerp_recouvrement",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/cron_data.xml",
        "views/lre_views.xml",
        "views/origines_views.xml",
    ],
    "installable": True,
    "application": False,
}
