from odoo import Command, models
from odoo.exceptions import UserError

TROU = "______________________"


def _euros(valeur):
    if valeur is None or valeur is False:
        return "__________ €"
    return "{:,.2f}".format(valeur).replace(",", " ").replace(".", ",") + " €"


def _date(d):
    return d.strftime("%d/%m/%Y") if d else "__/__/____"


class AssembleeGenerale(models.Model):
    _inherit = "coproerp.ag"

    def _points_ordinaires(self):
        """Ordre du jour type d'une assemblée générale ordinaire annuelle."""
        self.ensure_one()
        cloture = self.cloture_id
        annexes = cloture.donnees_annexes() if cloture else None
        budget_clos = cloture.budget_id
        en_cours = cloture.budget_en_cours_id
        a_voter = cloture.budget_a_voter_id
        points = []

        def rubrique(titre):
            points.append({"titre": titre, "majorite": "rubrique"})

        def point(titre, majorite, texte, documents=False):
            points.append({"titre": titre, "majorite": majorite, "texte": texte, "documents": documents})

        rubrique("BUREAU DE L'ASSEMBLÉE")
        point("Élection du président de séance", "art24",
              "L'assemblée générale désigne en qualité de président de séance : %s." % TROU)
        point("Élection du ou des scrutateurs", "art24",
              "L'assemblée générale désigne en qualité de scrutateur(s) : %s." % TROU)
        point("Désignation du secrétaire de séance", "art24",
              "Conformément à l'article 15 du décret du 17 mars 1967, le secrétariat de la séance est "
              "assuré par le syndic, sauf décision contraire de l'assemblée générale, qui désigne : %s." % TROU)

        rubrique("COMPTES ET BUDGETS")
        if annexes:
            charges = annexes["annexe2"]["courant"]["total_charges"]["n"]
            point("Approbation des comptes de l'exercice du %s au %s" % (
                _date(budget_clos.date_debut), _date(budget_clos.date_fin)), "art24",
                "L'assemblée générale, après avoir pris connaissance des documents comptables joints à la "
                "convocation (annexes 1 à 5 prévues par le décret n° 2005-240 du 14 mars 2005), approuve "
                "les comptes de l'exercice du %s au %s, dont le montant des charges pour opérations "
                "courantes s'élève à %s TTC, ainsi que leur répartition entre les copropriétaires."
                % (_date(budget_clos.date_debut), _date(budget_clos.date_fin), _euros(charges)),
                "Annexes comptables 1 à 5")
            if annexes["annexe4"]:
                for operation in annexes["annexe4"]:
                    if not operation["travaux"]:
                        continue
                    point("Approbation du compte des travaux : %s" % operation["travaux"].name, "art24",
                          "L'assemblée générale approuve le compte des travaux « %s » (annexe 4), dont les "
                          "dépenses de l'exercice s'élèvent à %s TTC, ainsi que leur répartition entre les "
                          "copropriétaires." % (operation["travaux"].name, _euros(operation["total_charges"]["n"])),
                          "Annexe 4")
        else:
            point("Approbation des comptes de l'exercice", "art24",
                  "L'assemblée générale, après avoir pris connaissance des documents comptables joints à la "
                  "convocation, approuve les comptes de l'exercice du __/__/____ au __/__/____, dont le "
                  "montant des charges pour opérations courantes s'élève à %s TTC, ainsi que leur "
                  "répartition entre les copropriétaires." % _euros(None))
        point("Quitus au syndic", "art24",
              "L'assemblée générale donne quitus au syndic pour sa gestion de l'exercice écoulé.")
        if en_cours:
            point("Actualisation du budget prévisionnel de l'exercice %s" % (en_cours.exercice or ""), "art24",
                  "L'assemblée générale actualise le budget prévisionnel de l'exercice du %s au %s, voté pour "
                  "%s, et le fixe à la somme de %s TTC." % (
                      _date(en_cours.date_debut), _date(en_cours.date_fin),
                      _euros(sum(en_cours.ligne_ids.mapped("montant_annuel")) or en_cours.budget_previsionnel),
                      _euros(None)),
                  "Budget prévisionnel")
        montant = (sum(a_voter.ligne_ids.mapped("montant_annuel")) or a_voter.budget_previsionnel) if a_voter else None
        point("Vote du budget prévisionnel de l'exercice %s" % (a_voter.exercice if a_voter else "suivant"), "art24",
              "L'assemblée générale approuve le budget prévisionnel de l'exercice du %s au %s pour un montant "
              "de %s TTC, réparti selon les clés figurant au document joint. Conformément à l'article 14-1 de "
              "la loi du 10 juillet 1965, les provisions sont exigibles le premier jour de chaque trimestre."
              % (_date(a_voter.date_debut if a_voter else None), _date(a_voter.date_fin if a_voter else None),
                 _euros(montant)),
              "Budget prévisionnel")
        cotisation = a_voter.cotisation_annuelle_fonds if a_voter else None
        point("Montant de la cotisation annuelle au fonds de travaux", "art25",
              "Conformément à l'article 14-2-1 de la loi du 10 juillet 1965, l'assemblée générale fixe le "
              "montant de la cotisation annuelle au fonds de travaux à %s, montant qui ne peut être inférieur "
              "à 5 %% du budget prévisionnel (et, en cas de plan pluriannuel de travaux adopté, à 2,5 %% du "
              "montant des travaux prévus). Les sommes versées sont attachées aux lots et définitivement "
              "acquises au syndicat ; elles ne donnent pas lieu à remboursement lors de la cession d'un lot."
              % _euros(cotisation or None))

        rubrique("SYNDIC ET CONSEIL SYNDICAL")
        point("Désignation du syndic", "art25",
              "L'assemblée générale désigne en qualité de syndic %s, pour une durée de %s à compter du %s, "
              "selon le contrat joint à la convocation (contrat type prévu par le décret n° 2015-342 du "
              "26 mars 2015), moyennant une rémunération forfaitaire annuelle de %s TTC, et mandate le "
              "président de séance pour signer le contrat." % (TROU, "____ mois", "__/__/____", _euros(None)),
              "Projet de contrat de syndic")
        point("Désignation des membres du conseil syndical", "art25",
              "L'assemblée générale désigne en qualité de membre(s) du conseil syndical, pour une durée de "
              "____ an(s) : %s." % TROU)
        point("Montant des marchés et contrats à partir duquel la consultation du conseil syndical est "
              "obligatoire", "art25",
              "En application de l'article 21 de la loi du 10 juillet 1965, l'assemblée générale fixe à %s TTC "
              "le montant des marchés et contrats à partir duquel la consultation du conseil syndical est "
              "obligatoire." % _euros(None))
        point("Montant des marchés et contrats à partir duquel une mise en concurrence est obligatoire", "art25",
              "En application de l'article 21 de la loi du 10 juillet 1965, l'assemblée générale fixe à %s TTC "
              "le montant des marchés et contrats à partir duquel une mise en concurrence est obligatoire."
              % _euros(None))

        rubrique("QUESTIONS DIVERSES")
        point("Questions diverses", "information",
              "Échanges sans vote : l'assemblée générale ne peut délibérer valablement que sur les questions "
              "inscrites à l'ordre du jour (art. 13 du décret du 17 mars 1967).")
        return points

    def action_ordre_du_jour_type(self):
        for ag in self:
            if ag.etat != "preparation":
                raise UserError("L'ordre du jour ne peut être modifié qu'en préparation.")
            if ag.resolution_ids:
                raise UserError("L'ordre du jour n'est pas vide : supprimez les points existants avant de "
                                "charger l'ordre du jour type.")
            points = ag._points_ordinaires()
            ag.write({"resolution_ids": [
                Command.create(dict(p, sequence=(i + 1) * 10)) for i, p in enumerate(points)]})
            if not ag.documents_joints:
                docs = ["Projet de résolutions", "Formulaire de vote par correspondance", "Pouvoir"]
                if ag.cloture_id:
                    docs.insert(0, "Comptes de l'exercice : annexes comptables 1 à 5")
                docs.insert(1 if ag.cloture_id else 0, "Budget prévisionnel")
                docs.insert(2 if ag.cloture_id else 1, "Projet de contrat de syndic et fiche d'information")
                ag.documents_joints = "\n".join(docs)
            ag.action_renumeroter()
        return True
