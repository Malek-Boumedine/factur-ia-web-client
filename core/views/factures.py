"""Vues du domaine factures.

Pour l'instant, seul le placeholder du récapitulatif human-in-the-loop est
présent : il matérialise la cible de redirection de l'écran d'attente
(`documents/<id>/attente/`) une fois l'extraction terminée. La vérification
et la validation des données extraites arrivent dans la tâche suivante.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.views.auth import _guard_entreprise


def facture_recap_view(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Affiche le récapitulatif (placeholder) d'un brouillon de facture.

    Cible de la redirection post-extraction : le brouillon `facture_id` a été
    créé par l'OCR. L'écran de vérification human-in-the-loop remplacera ce
    placeholder dans la tâche suivante.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        facture_id (int): Identifiant du brouillon de facture créé par
            l'extraction. Obligatoire.

    Returns:
        HttpResponse: Rendu du placeholder, ou redirection du garde-fou
        (login/onboarding) si la session ne le permet pas.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    return render(request, "core/facture_recap.html", {"facture_id": facture_id})
