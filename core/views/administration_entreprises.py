"""Vues d'administration des entreprises abonnées (backoffice plateforme).

Réservées aux administrateurs de plateforme (garde-fou de session
`is_platform_admin`, l'API restant juge de vérité). Ces écrans agissent sur
n'importe quelle entreprise : les appels passent par `AdministrationClient`,
qui ne transmet pas le header de tenant.

Ce module couvre pour l'instant la liste (recherche, filtres statut
d'abonnement et actif/suspendu, pagination — état porté par les query params)
et les actions de suspension et de réactivation. La suspension est réversible
et sans perte : c'est la réponse recommandée face à une entreprise dont les
données interdisent la suppression.

Tout appel réseau passe par la couche `clients/`.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from clients.administration_client import AdministrationClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from core.pagination import (
    PAGE_SIZE,
    base_querystring,
    build_pagination,
    parse_bool_filter,
    parse_page,
)
from core.views.abonnements import _guard_platform_admin, _refus_api
from core.views.administration import (
    STATUTS_SOUSCRIPTION,
    STATUTS_SOUSCRIPTION_VALUES,
    relay_guard_refusal,
    with_display_souscription,
)
from core.views.auth import _MSG_INDISPONIBLE

# Longueur maximale du motif de suspension acceptée par l'API
# (schéma SuspensionRequest).
_MOTIF_MAX_LENGTH = 255


def administration_entreprises_view(request: HttpRequest) -> HttpResponse:
    """Liste les entreprises abonnées avec leurs actions de gestion."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    # Lecture défensive des query params.
    search = request.GET.get("q", "").strip()
    est_actif_raw = request.GET.get("est_actif", "")
    est_actif = parse_bool_filter(est_actif_raw)
    statut_raw = request.GET.get("statut", "")
    statut = statut_raw if statut_raw in STATUTS_SOUSCRIPTION_VALUES else ""
    page = parse_page(request.GET.get("page"))
    skip = (page - 1) * PAGE_SIZE

    items: list = []
    total = 0
    try:
        result = AdministrationClient(request).list_entreprises(
            recherche=search or None,
            est_actif=est_actif,
            statut_abonnement=statut or None,
            skip=skip,
            limit=PAGE_SIZE,
        )
        items = with_display_souscription(result.get("items", []))
        total = result.get("total", 0)
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        # En lecture, un 403 ne peut signifier qu'un accès refusé.
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Impossible de charger la liste des entreprises.")

    pagination = build_pagination(page, total)

    context = {
        "items": items,
        "total": total,
        "base_query": base_querystring(request),
        # Valeurs courantes des filtres, pour ré-afficher l'état du formulaire.
        "search": search,
        "est_actif": est_actif_raw,
        "statut": statut,
        "statuts": STATUTS_SOUSCRIPTION,
        "motif_max_length": _MOTIF_MAX_LENGTH,
        **pagination,
    }
    return render(request, "core/administration_entreprises.html", context)


@require_POST
def administration_entreprise_suspend_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Suspend une entreprise (motif optionnel), puis revient à la liste."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    motif = request.POST.get("motif", "").strip()[:_MOTIF_MAX_LENGTH]

    try:
        AdministrationClient(request).suspend_entreprise(entreprise_id, motif or None)
        messages.success(
            request,
            "L'entreprise a été suspendue : ses membres n'ont plus accès à leur "
            "espace de travail.",
        )
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise introuvable.")
    except APIValidationError as e:
        relay_guard_refusal(request, e.detail, "Suspension refusée.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        # En action, un 403 porte un garde-fou métier : on relaie son message.
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Suspension refusée.")
        else:
            messages.error(request, "Erreur lors de la suspension de l'entreprise.")

    return _redirect_liste(request)


@require_POST
def administration_entreprise_reactivate_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Réactive une entreprise suspendue, puis revient à la liste."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        AdministrationClient(request).reactivate_entreprise(entreprise_id)
        messages.success(
            request,
            "L'entreprise a été réactivée : ses membres retrouvent l'accès à "
            "leur espace de travail.",
        )
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise introuvable.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Réactivation refusée.")
        else:
            messages.error(request, "Erreur lors de la réactivation de l'entreprise.")

    return _redirect_liste(request)


def _redirect_liste(request: HttpRequest) -> HttpResponse:
    """Redirige vers la liste en préservant recherche, filtres et page.

    L'état de la liste vit dans les query params : après une action, on y
    revient tel quel plutôt que sur une liste remise à zéro. Le champ `retour`
    est posé par le formulaire appelant ; il est ré-encodé avant usage (sa
    valeur vient du client et ne doit pas partir telle quelle dans l'en-tête
    `Location`).
    """
    query = QueryDict(request.POST.get("retour", "")).urlencode()
    url = reverse("admin_entreprises")
    return redirect(f"{url}?{query}" if query else url)
