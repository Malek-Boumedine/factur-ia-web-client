"""Utilitaires de pagination et de filtres pour les vues de liste.

Ces helpers traduisent les query params d'une page Django (recherche, filtres,
numéro de page 1-based) vers les paramètres attendus par la couche `clients/`
(offset `skip`/`limit`), puis reconstruisent les informations de pagination à
présenter au template une fois le total connu.
"""

import math
from typing import Any

from django.http import HttpRequest

# Nombre d'éléments par page, commun à toutes les listes.
PAGE_SIZE = 20


def parse_page(raw: Any) -> int:
    """Interprète le paramètre `page` de façon défensive.

    Args:
        raw (Any): Valeur brute issue de `request.GET` (str ou None).

    Returns:
        int: Le numéro de page (1-based). Toute valeur absente, non numérique
        ou inférieure à 1 est repliée sur 1.
    """
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return 1
    return page if page >= 1 else 1


def parse_bool_filter(raw: Any) -> bool | None:
    """Interprète un filtre booléen ternaire depuis un query param.

    Args:
        raw (Any): Valeur brute (`"true"`, `"false"` ou autre/vide).

    Returns:
        bool | None: `True`/`False` pour un filtre explicite, `None` lorsque le
        filtre n'est pas appliqué (option « Tous »).
    """
    if raw == "true":
        return True
    if raw == "false":
        return False
    return None


def build_pagination(
    page: int, total: int, page_size: int = PAGE_SIZE
) -> dict[str, Any]:
    """Construit le contexte de pagination à partir du total renvoyé par l'API.

    Le numéro de page affiché est clampé à l'intervalle valide : une page
    demandée au-delà du dernier index (URL forgée ou liste réduite par un
    filtre) retombe sur la dernière page existante.

    Args:
        page (int): Numéro de page demandé (déjà passé par `parse_page`).
        total (int): Nombre total d'éléments renvoyé par l'API (tous filtres
            appliqués).
        page_size (int): Taille de page. Défaut `PAGE_SIZE`.

    Returns:
        dict: Contexte prêt pour le template avec `page` (clampé),
        `total_pages`, `has_previous`/`has_next` et `previous_page`/`next_page`.
    """
    total_pages = max(1, math.ceil(total / page_size)) if total else 1
    page = min(max(page, 1), total_pages)
    return {
        "page": page,
        "total_pages": total_pages,
        "has_previous": page > 1,
        "has_next": page < total_pages,
        "previous_page": page - 1,
        "next_page": page + 1,
    }


def base_querystring(request: HttpRequest) -> str:
    """Reconstruit la query string courante sans le paramètre `page`.

    Permet de bâtir les liens de pagination en préservant recherche et filtres :
    le template n'a plus qu'à y ajouter `&page=N`.

    Args:
        request (HttpRequest): Requête courante.

    Returns:
        str: Query string urlencodée (sans `page`, sans `?` initial), ou chaîne
        vide si aucun autre paramètre n'est présent.
    """
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()
