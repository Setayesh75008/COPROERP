# CoproERP – Extranet copropriétaires

Espace en ligne sécurisé des copropriétaires (art. 18 de la loi du 10 juillet 1965,
décret n° 2019-502 du 23 mai 2019), intégré au portail d'Odoo 19.

## Qui a accès

| Qui | Accès |
|---|---|
| Propriétaire, usufruitier, nu-propriétaire, indivisaire (fiche **Droit** en cours) | Son immeuble, ses lots, sa situation, les documents communs et ses documents personnels |
| Membre du conseil syndical (**mandat en cours**) | En plus : solde de tous les copropriétaires de l'immeuble, relevé des dépenses, documents réservés au CS |
| Locataire | Aucun accès |
| Droit terminé (lot vendu) ou mandat terminé | Accès retiré automatiquement (à la saisie de la date de fin, et chaque nuit) |

Le cloisonnement est appliqué **par la base de données** (règles d'accès
`security/extranet_security.xml`) : même en modifiant l'adresse d'une page,
un copropriétaire ne peut pas lire les données d'un autre.

## Installation

1. Copier le dossier `coproerp_extranet` dans `custom_addons`, ainsi que les
   corrections apportées à `coproerp_batiment`, `coproerp_lot`, `coproerp_droit`
   (droits d'accès) et `coproerp_copropriete` (méthode `action_view_batiments`).
2. Redémarrer Odoo, puis *Applications → Mettre à jour la liste des applications*.
3. Mettre à jour `coproerp_batiment`, `coproerp_lot`, `coproerp_droit`,
   `coproerp_copropriete`, puis installer **CoproERP - Extranet copropriétaires**.

En ligne de commande :

```
python odoo-bin -c odoo.conf -d COPROERP-dev -u coproerp_batiment,coproerp_lot,coproerp_droit,coproerp_copropriete -i coproerp_extranet --stop-after-init
```

## Tests automatiques (sur une base de test)

```
python odoo-bin -c odoo.conf -d COPROERP-test -i coproerp_extranet --test-tags /coproerp_extranet --stop-after-init
```

Les tests vérifient notamment : un propriétaire ne voit ni les appels ni les
documents personnels d'un autre, ni un autre immeuble ; le locataire n'a
aucun accès ; le conseiller syndical voit les soldes pendant son mandat et plus
après ; la vente d'un lot coupe l'accès ; les pages réservées au conseil
syndical sont refusées aux autres copropriétaires.

## Mise en route pour un immeuble

1. Fiche copropriété → onglet **Extranet** : gestionnaire, comptable, IBAN du
   compte séparé, message d'accueil, e-mail de contact.
2. Fiche copropriété → onglet **Conseil syndical** : saisir les mandats (dates).
3. Vérifier les fiches **Droit** (type, dates de début / fin).
4. Fiche contact → onglet **Extranet** → *Donner l'accès à l'extranet*
   (envoie l'invitation avec création du mot de passe).
5. Menu *CoproERP → Extranet → Documents* : déposer, choisir la visibilité,
   cliquer sur **Publier** (alerte e-mail aux personnes concernées).

## Pages de l'extranet

`/extranet` tableau de bord · `/extranet/lots` · `/extranet/situation` (ma situation, export Excel) ·
`/extranet/situation/coproprietaires` (CS) · `/extranet/situation/depenses` (CS par défaut) ·
`/extranet/documents` · `/extranet/dematerialisation` · `/extranet/actualites` ·
`/extranet/reglement` · `/extranet/compte`

## Points d'extension prévus

- **Règlements** : compléter `coproerp.copropriete._extranet_mouvements()` avec les
  écritures au crédit ; le solde, la page « Ma situation » et le solde par
  copropriétaire les prendront en compte sans autre modification.
- **Dépenses** : compléter `coproerp.copropriete._extranet_depenses()`.
