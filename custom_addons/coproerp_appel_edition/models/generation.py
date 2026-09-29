"""Moteur commun de génération des appels de fonds.

Utilisé par :
- le budget (appels du budget courant et du fonds travaux) ;
- l'échéancier des travaux (appels exceptionnels).

Règles :
- un seul appel par destinataire et par échéance, regroupant tous ses lots ;
- un lot sans part dans une clé n'a pas de ligne pour cette clé ;
- un lot sans aucune part n'apparaît pas ; un destinataire sans lot non plus ;
- la génération est arrêtée, sans rien créer, si un lot concerné n'a pas de
  destinataire identifiable (plusieurs titulaires sans mandataire commun...) ;
- une échéance déjà générée pour un destinataire n'est pas recréée.
"""

from collections import OrderedDict

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round


class AppelChargeGeneration(models.Model):
    _inherit = "coproerp.appel.charge"

    @api.model
    def _periodes(self, date_debut, nombre_appels):
        """Découpe l'exercice en périodes de mois entiers.

        4 appels -> trimestres, 2 -> semestres, 12 -> mois, 1 -> année.
        Retourne une liste de (numero, debut, fin).
        """
        if nombre_appels not in (1, 2, 3, 4, 6, 12):
            raise UserError(
                "Le nombre d'appels doit diviser l'année en périodes de mois "
                "entiers : 1, 2, 3, 4, 6 ou 12."
            )
        mois = 12 // nombre_appels
        date_debut = fields.Date.to_date(date_debut)
        periodes = []
        for numero in range(1, nombre_appels + 1):
            debut = date_debut + relativedelta(months=mois * (numero - 1))
            fin = debut + relativedelta(months=mois, days=-1)
            periodes.append((numero, debut, fin))
        return periodes

    @api.model
    def _generer_appels(self, copropriete, lignes, vals_appel, domaine_existant,
                        date_ref=None):
        """Crée les appels d'une échéance.

        :param copropriete: coproerp.copropriete
        :param lignes: liste de dicts
            {type_poste, designation, repartition (record), montant}
            où ``montant`` est le total à répartir pour cette échéance.
        :param vals_appel: valeurs communes des appels (type, dates, liens...)
        :param domaine_existant: domaine permettant de retrouver un appel déjà
            généré pour cette échéance (complété par le destinataire)
        :return: (appels créés, liste des messages d'information)
        """
        lignes = [l for l in lignes if l["montant"]]
        if not lignes:
            return self.browse(), []

        # Parts de chaque lot dans chaque clé
        parts = {}
        for ligne in lignes:
            cle = ligne["repartition"]
            if not cle:
                raise UserError(
                    "La ligne « %s » n'a pas de clé de répartition." % ligne["designation"]
                )
            if cle.copropriete_id != copropriete:
                raise UserError(
                    "La clé « %s » n'appartient pas à la copropriété %s."
                    % (cle.name, copropriete.name)
                )
            if not cle.total_tantiemes:
                raise UserError("La clé « %s » n'a pas de total de tantièmes." % cle.name)
            parts[cle.id] = {l.lot_id.id: l.tantiemes for l in cle.line_ids if l.tantiemes}

        lots_concernes = self.env["coproerp.lot"].browse(
            sorted({lot_id for p in parts.values() for lot_id in p})
        ).filtered(lambda l: l.active and not l.propriete_syndicat)

        # Destinataires : on vérifie tout avant de créer quoi que ce soit.
        par_destinataire = OrderedDict()
        erreurs = []
        for lot in lots_concernes.sorted(lambda l: (l.numero or "")):
            destinataire, erreur = lot._destinataire_appels(date_ref)
            if erreur:
                erreurs.append(erreur)
                continue
            if destinataire:
                par_destinataire.setdefault(destinataire, self.env["coproerp.lot"])
                par_destinataire[destinataire] |= lot
        if erreurs:
            raise UserError(
                "Génération impossible, aucun appel n'a été créé :\n- "
                + "\n- ".join(erreurs)
            )

        Groupe = self.env["coproerp.appel.charge.groupe"]
        Poste = self.env["coproerp.appel.charge.poste"]
        crees = self.browse()
        for destinataire, lots in sorted(
            par_destinataire.items(), key=lambda item: (item[0].name or "").lower()
        ):
            if self.search_count(domaine_existant + [("personne_id", "=", destinataire.id)]):
                continue
            appel = self.create(dict(vals_appel, personne_id=destinataire.id,
                                     copropriete_id=copropriete.id))
            for lot in lots:
                lignes_lot = [l for l in lignes if parts[l["repartition"].id].get(lot.id)]
                if not lignes_lot:
                    continue
                groupe = Groupe.create({"appel_id": appel.id, "lot_id": lot.id})
                for sequence, ligne in enumerate(lignes_lot, start=1):
                    Poste.create({
                        "groupe_id": groupe.id,
                        "sequence": sequence * 10,
                        "type_poste": ligne["type_poste"],
                        "designation": ligne["designation"],
                        "repartition_id": ligne["repartition"].id,
                        "total_a_repartir": ligne["montant"],
                    })
            crees |= appel

        # Contrôle des arrondis : somme appelée vs total à répartir
        messages = []
        if crees:
            postes = crees.groupe_ids.poste_ids
            for ligne in lignes:
                appele = sum(
                    postes.filtered(
                        lambda p: p.repartition_id == ligne["repartition"]
                        and p.designation == ligne["designation"]
                    ).mapped("montant_appel")
                )
                ecart = float_round(ligne["montant"] - appele, precision_digits=2)
                if abs(ecart) >= 0.01:
                    messages.append(
                        "%s : total à répartir %.2f €, appelé %.2f € (écart d'arrondi "
                        "ou part non attribuée %.2f €)."
                        % (ligne["designation"], ligne["montant"], appele, ecart)
                    )
        return crees, messages

    @api.model
    def _action_resultat(self, appels, titre, messages):
        """Ouvre la liste des appels créés, avec un message récapitulatif."""
        liste = {
            "type": "ir.actions.act_window",
            "name": titre,
            "res_model": "coproerp.appel.charge",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": [("id", "in", appels.ids)],
        }
        texte = "%s appel(s) créé(s)." % len(appels)
        if not appels:
            texte = "Aucun nouvel appel : cette échéance a déjà été générée."
        if messages:
            texte += "\n" + "\n".join(messages)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": titre,
                "message": texte,
                "type": "warning" if messages or not appels else "success",
                "sticky": bool(messages),
                "next": liste,
            },
        }
