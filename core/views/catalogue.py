"""Vue de liste du catalogue : recherche, filtres et pagination.

L'état (recherche, filtres actif/inactif et type de produit, page) est porté
par les query params de l'URL, ce qui rend la page partageable et rechargeable.
Tout appel réseau passe par la couche `clients/`.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.exceptions import APIClientError, APIUnavailableError, TokenExpiredError
from clients.produits_client import ProduitsClient
from core.pagination import (
    PAGE_SIZE,
    base_querystring,
    build_pagination,
    parse_bool_filter,
    parse_page,
)

# Types de produit exposés par l'enum métier TypeProduit du contrat OpenAPI.
# Clé = valeur transmise à l'API (ne pas traduire) ; libellé = affichage FR.
TYPES_PRODUIT = [
    ("produit", "Produit"),
    ("prestation", "Prestation"),
    ("service", "Service"),
]
_TYPES_PRODUIT_VALUES = {value for value, _ in TYPES_PRODUIT}


def catalogue_list_view(request: HttpRequest) -> HttpResponse:
    """Affiche la liste paginée et filtrée du catalogue de l'entreprise active."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    # Lecture défensive des query params.
    search = request.GET.get("q", "").strip()
    est_actif_raw = request.GET.get("est_actif", "")
    est_actif = parse_bool_filter(est_actif_raw)
    type_produit_raw = request.GET.get("type_produit", "")
    # On ne transmet le type que s'il fait partie de l'enum métier.
    type_produit = (
        type_produit_raw if type_produit_raw in _TYPES_PRODUIT_VALUES else None
    )
    page = parse_page(request.GET.get("page"))
    skip = (page - 1) * PAGE_SIZE

    client = ProduitsClient(request)

    items: list = []
    total = 0
    try:
        result = client.list_products(
            search=search or None,
            est_actif=est_actif,
            type_produit=type_produit,
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
            request, f"Erreur lors du chargement du catalogue ({e.status_code})."
        )

    pagination = build_pagination(page, total)

    context = {
        "items": items,
        "total": total,
        "base_query": base_querystring(request),
        "types_produit": TYPES_PRODUIT,
        # Valeurs courantes des filtres, pour ré-afficher l'état du formulaire.
        "search": search,
        "est_actif": est_actif_raw,
        "type_produit": type_produit or "",
        **pagination,
    }
    return render(request, "core/catalogue.html", context)
