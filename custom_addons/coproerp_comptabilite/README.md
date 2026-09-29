# CoproERP – Comptabilité des copropriétés

## Mise en route (par copropriété)
1. Fiche copropriété → onglet **Comptabilité** → **Créer le dossier comptable** :
   crée « SDC <nom> » (société Odoo dédiée), charge le plan comptable des syndicats
   (module coproerp_plan_comptable), les journaux APF (appels), BQ (banque), ACH (achats),
   OD, scellés (inaltérabilité) ; l'IBAN de l'onglet Extranet est rattaché au journal BQ.
2. Droits : les utilisateurs qui comptabilisent doivent avoir le droit
   *Comptabilité : Facturation* (ou Administrateur) dans *Paramètres → Utilisateurs*.

## Au quotidien
- **Appels** : après génération, bouton **Comptabiliser** (ou, depuis la liste, *Action →
  Comptabiliser les appels*). L'écriture est validée et scellée ; l'appel devient
  non modifiable. Correction : **Annuler (contre-passation)**, puis nouvel appel.
- **Règlements** : menu *CoproERP → Comptabilité → Règlements des copropriétaires* →
  **Valider et imputer** : imputation sur les appels les plus anciens, lettrage ;
  l'excédent reste au crédit et s'impute sur l'appel suivant. Impayé : **Annuler**.
- **Factures fournisseurs** : comptabilité Odoo standard (sélectionner « SDC … » en haut à
  droite), comptes 6xx / 401000.
- **Clôture** : onglet Comptabilité → **Mettre en réserve le fonds de travaux** (705 → 105).

## Écritures
| Opération | Débit | Crédit |
|---|---|---|
| Appel budget | 450010 | 701000 |
| Appel fonds de travaux | 450050 | 705000 |
| Appel travaux / hors budget | 450020 | 702000 |
| Appel d'avance | 450030 | 103100 |
| Règlement | 512000 | 450xxx (lettré) |
| Mise en réserve | 705000 | 105000 |

Numéros paramétrables sur la fiche copropriété ; plan modifiable dans
`coproerp_plan_comptable/data/template/account.account-copro_fr.csv`.

## À venir
Régularisation annuelle des charges (dépenses réelles − provisions appelées).
