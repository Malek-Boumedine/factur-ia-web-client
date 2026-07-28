"""Socle partagé des vues du backoffice d'administration plateforme.

Regroupe ce que les écrans « Entreprises » et « Utilisateurs » ont en commun :
les libellés d'affichage des statuts de souscription, et le relais des refus
métier de l'API.

Sur les routes `/administration`, un 403 recouvre deux situations distinctes :

- en **lecture** (listes, détails), il ne peut signifier que « appelant non
  administrateur de plateforme » — les vues le traitent alors comme un refus
  d'accès via `_refus_api` (redirection vers l'accueil) ;
- en **action** (suppression, désactivation...), il porte un garde-fou métier
  au message explicite (facture émise, compte protégé, auto-suppression). La
  vue reste alors sur place et affiche ce message via `relay_guard_refusal`.

La discrimination repose sur le type de route appelée, jamais sur le contenu
du message.
"""

from typing import Any

from django.contrib import messages
from django.http import HttpRequest

from core.formatting import format_iso_date_fr


# Statuts de souscription (enum StatutSouscription du contrat OpenAPI) : les
# clés sont les valeurs envoyées à l'API et ne doivent jamais être traduites,
# les libellés sont l'affichage FR.
STATUTS_SOUSCRIPTION = (
    ("actif", "Actif"),
    ("expiré", "Expiré"),
    ("suspendu", "Suspendu"),
    ("annulé", "Annulé"),
)
STATUTS_SOUSCRIPTION_VALUES = {value for value, _ in STATUTS_SOUSCRIPTION}
STATUT_LABELS = dict(STATUTS_SOUSCRIPTION)

# Couleur du badge daisyUI associée à chaque statut de souscription.
STATUT_BADGES = {
    "actif": "badge-success",
    "expiré": "badge-warning",
    "suspendu": "badge-warning",
    "annulé": "badge-error",
}


def with_display_souscription(entreprises: list) -> list:
    """Enrichit chaque entreprise des champs d'affichage de sa souscription.

    Ajoute `plan_libelle`, `statut_label` et `statut_badge` à partir de la
    souscription courante imbriquée, absente si l'entreprise n'a jamais
    souscrit.

    Args:
        entreprises (list): Entreprises renvoyées par l'API (schémas
            EntrepriseAdminListItem ou EntrepriseAdminDetail). Obligatoire.

    Returns:
        list: La même liste, enrichie sur place.
    """
    for entreprise in entreprises:
        souscription = entreprise.get("souscription") or {}
        # Chaîne vide si l'entreprise n'a jamais souscrit : le template affiche
        # alors « — » plutôt qu'un badge.
        statut = str(souscription.get("statut") or "")
        entreprise["plan_libelle"] = souscription.get("libelle_abonnement")
        entreprise["statut_label"] = STATUT_LABELS.get(statut, statut)
        entreprise["statut_badge"] = STATUT_BADGES.get(statut, "badge-ghost")
    return entreprises


def with_display_souscriptions(souscriptions: list) -> list:
    """Enrichit chaque souscription de ses champs d'affichage.

    Ajoute `statut_label`, `statut_badge` et les dates de début et de fin
    formatées à la française. Destiné à l'historique des souscriptions d'une
    entreprise (schéma SouscriptionAdminRead), du plus récent au plus ancien.

    Args:
        souscriptions (list): Souscriptions renvoyées par l'API. Obligatoire.

    Returns:
        list: La même liste, enrichie sur place.
    """
    for souscription in souscriptions:
        statut = str(souscription.get("statut") or "")
        souscription["statut_label"] = STATUT_LABELS.get(statut, statut)
        souscription["statut_badge"] = STATUT_BADGES.get(statut, "badge-ghost")
        souscription["date_debut_fr"] = format_iso_date_fr(
            souscription.get("date_debut")
        )
        souscription["date_fin_fr"] = format_iso_date_fr(souscription.get("date_fin"))
    return souscriptions


def relay_guard_refusal(request: HttpRequest, detail: Any, fallback: str) -> None:
    """Affiche le motif de refus renvoyé par l'API, ou un message de repli.

    Les garde-fous de l'administration (403 et 409) renvoient un `detail`
    rédigé pour être lu par l'administrateur : il est affiché tel quel. Le repli
    couvre le cas d'un corps vide ou d'une forme inattendue (liste d'erreurs de
    validation, par exemple).

    Args:
        request (HttpRequest): Requête courante. Obligatoire.
        detail (Any): Champ `detail` porté par l'exception. Obligatoire.
        fallback (str): Message affiché si `detail` n'est pas exploitable.
            Obligatoire.
    """
    message = detail if isinstance(detail, str) and detail.strip() else fallback
    messages.error(request, message)
