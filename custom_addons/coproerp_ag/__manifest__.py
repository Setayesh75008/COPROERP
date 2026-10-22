{
    "name": "CoproERP - Assemblées générales (préparation et convocation)",
    "summary": "Ordre du jour, projets de résolution, convocations, vote par correspondance et pouvoir",
    "description": """
Préparation de l'assemblée générale des copropriétaires :

- fiche de l'assemblée (date, heure, lieu, visioconférence) ;
- ordre du jour et projets de résolution avec leur majorité (art. 24, 25 et
  passerelle 25-1, 26 et second vote, unanimité, information sans vote) ;
  ordre du jour type d'une assemblée ordinaire pré-rempli à partir des comptes
  clôturés et des budgets ;
- liste des convocations : destinataire de chaque lot (mandataire commun en cas
  d'indivision ou de démembrement), voix (tantièmes généraux), mode de
  notification (lettre recommandée électronique par défaut, postale sur
  demande, art. 42-1), contrôle du délai de 21 jours (art. 9 et 64 du décret) ;
- dossier de convocation par copropriétaire : lettre et ordre du jour,
  mentions légales (mandats art. 22, vote par correspondance art. 17-1 A et
  9 bis du décret, pièces justificatives art. 18-1), projet de résolutions,
  formulaire de vote par correspondance et pouvoir.
""",
    "author": "SSB AVOCAT",
    "website": "https://www.ssb-avocat.fr",
    "category": "Real Estate",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "depends": [
        "coproerp_cloture",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ag_views.xml",
        "report/ag_report.xml",
        "report/ag_templates.xml",
    ],
    "installable": True,
    "application": False,
}
