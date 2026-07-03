from decimal import Decimal, InvalidOperation

from django.shortcuts import render

from clients.abonnements_client import AbonnementsClient
from clients.exceptions import APIClientError
from core.views.abonnements import _format_tarif


def _tarif_value(plan: dict) -> Decimal:
    """Valeur numérique du tarif d'un plan (0 si absent ou illisible)."""
    try:
        return Decimal(str(plan.get("tarif")))
    except (InvalidOperation, TypeError):
        return Decimal(0)


def _prepare_plans(plans: list) -> tuple[list, int | None]:
    """Enrichit les plans pour l'affichage vitrine et désigne le plan à mettre
    en avant.

    Chaque plan reçoit `tarif_affiche` (tarif formaté à la française, via le
    helper partagé) et `is_gratuit`. Le plan « recommandé » retenu est le plus
    premium (tarif le plus élevé) : choix produit best-effort côté vitrine,
    l'API n'exposant pas de plan « populaire ». Renvoie `(plans, featured_id)`.
    """
    featured_id: int | None = None
    meilleur = Decimal(0)
    for plan in plans:
        valeur = _tarif_value(plan)
        plan["tarif_affiche"] = _format_tarif(plan.get("tarif"))
        plan["is_gratuit"] = valeur == 0
        if valeur > meilleur:
            meilleur = valeur
            featured_id = plan.get("id")
    return plans, featured_id


def home_view(request):
    """Affiche la page d'accueil (vitrine publique).

    Page marketing accessible à tous ; l'en-tête et les CTA s'adaptent à l'état
    d'authentification (session). La grille tarifaire présente les plans réels
    exposés par l'API (GET /abonnements/, route publique). En cas d'API
    injoignable ou d'erreur, on dégrade proprement : aucun plan dynamique n'est
    passé au template (`plans=None`), la page reste servie sans planter.
    """
    try:
        raw = AbonnementsClient(request).list_subscriptions()
    except APIClientError:
        raw = None
    plans, featured_id = _prepare_plans(raw) if isinstance(raw, list) else (None, None)
    return render(
        request,
        "core/home.html",
        {"plans": plans, "featured_plan_id": featured_id},
    )
