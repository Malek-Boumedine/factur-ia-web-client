"""Vue de liste des clients : recherche, filtre actif/inactif et pagination.

L'état (recherche, filtre, page) est porté par les query params de l'URL, ce
qui rend la page partageable et rechargeable. Tout appel réseau passe par la
couche `clients/`.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.clients_client import ClientsClient
from clients.exceptions import APIClientError, APIUnavailableError, TokenExpiredError
from core.pagination import (
    PAGE_SIZE,
    base_querystring,
    build_pagination,
    parse_bool_filter,
    parse_page,
)


def clients_list_view(request: HttpRequest) -> HttpResponse:
    """Affiche la liste paginée et filtrée des clients de l'entreprise active."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    # Lecture défensive des query params.
    search = request.GET.get("q", "").strip()
    est_actif_raw = request.GET.get("est_actif", "")
    est_actif = parse_bool_filter(est_actif_raw)
    page = parse_page(request.GET.get("page"))
    skip = (page - 1) * PAGE_SIZE

    client = ClientsClient(request)

    items: list = []
    total = 0
    try:
        result = client.list_clients(
            search=search or None,
            est_actif=est_actif,
            skip=skip,
            limit=PAGE_SIZE,
        )
        items = result.get("items", [])
        total = result.get("total", 0)
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(
            request, "Service momentanément indisponible. Veuillez réessayer."
        )
    except APIClientError as e:
        messages.error(
            request, f"Erreur lors du chargement des clients ({e.status_code})."
        )

    pagination = build_pagination(page, total)

    context = {
        "items": items,
        "total": total,
        "base_query": base_querystring(request),
        # Valeurs courantes des filtres, pour ré-afficher l'état du formulaire.
        "search": search,
        "est_actif": est_actif_raw,
        **pagination,
    }
    return render(request, "core/clients.html", context)
