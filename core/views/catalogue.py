"""Vues du domaine catalogue produits.

Liste (recherche, filtres actif/inactif et type de produit, pagination — état
porté par les query params de l'URL), création, détail, édition et
désactivation (soft delete côté API). Les taux de TVA des formulaires
proviennent de GET /taux-tva/. Tout appel réseau passe par la couche `clients/`.
"""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from clients.produits_client import ProduitsClient
from clients.taux_tva_client import TauxTvaClient
from core.constants import TYPES_PRODUIT, TYPES_PRODUIT_VALUES
from core.forms import CatalogueForm
from core.views.auth import (
    _MSG_INDISPONIBLE,
    _appliquer_erreur_conflit,
    _appliquer_erreurs_api,
)
from core.pagination import (
    PAGE_SIZE,
    base_querystring,
    build_pagination,
    parse_bool_filter,
    parse_page,
)


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
        type_produit_raw if type_produit_raw in TYPES_PRODUIT_VALUES else None
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


# Rattachement des messages de conflit 409 aux champs du formulaire produit :
# mot-clé (minuscule) recherché dans le message de l'API -> champ concerné.
# (Aucun conflit documenté au contrat pour le catalogue à ce jour : traitement
# défensif pour afficher proprement le message si l'API en renvoie un.)
_CONFLICT_FIELD_KEYWORDS = {
    "référence": "reference",
    "reference": "reference",
    "désignation": "designation",
    "designation": "designation",
}


def _format_taux_label(taux: dict) -> str:
    """Construit le libellé affiché d'un taux de TVA (ex : « Taux normal — 20 % »).

    La valeur `taux` arrive en chaîne (ex : "20.00") : on retire les zéros non
    significatifs et on affiche la virgule décimale française.
    """
    libelle = taux.get("libelle", "")
    try:
        value = format(Decimal(str(taux.get("taux"))).normalize(), "f")
    except (InvalidOperation, TypeError):
        return libelle
    return f"{libelle} — {value.replace('.', ',')} %"


def _load_taux_choices(request: HttpRequest) -> list[tuple[int, str]]:
    """Charge les taux de TVA actifs pour le menu déroulant du formulaire.

    En cas d'échec de l'appel API (hors 401, qui se propage), on affiche un
    message clair et on renvoie une liste vide : le formulaire reste affiché
    mais ne peut pas être soumis sans taux valide.
    """
    try:
        taux_list = TauxTvaClient(request).list_taux(est_actif=True)
    except TokenExpiredError:
        raise
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return []
    except APIClientError:
        messages.error(
            request,
            "Impossible de charger les taux de TVA. "
            "Le formulaire ne peut pas être soumis pour le moment.",
        )
        return []
    return [(t["id"], _format_taux_label(t)) for t in taux_list]


def catalogue_create_view(request: HttpRequest) -> HttpResponse:
    """Crée un produit du catalogue."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    try:
        taux_choices = _load_taux_choices(request)
    except TokenExpiredError:
        return redirect("login")

    if request.method == "POST":
        form = CatalogueForm(request.POST, taux_choices=taux_choices)
        if form.is_valid():
            try:
                created = ProduitsClient(request).create_product(form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de la création du produit.")
            else:
                messages.success(request, "Le produit a été créé avec succès.")
                return redirect("catalogue_detail", produit_id=created["id"])
    else:
        form = CatalogueForm(taux_choices=taux_choices)

    return render(request, "core/catalogue_form.html", {"form": form, "is_edit": False})


def catalogue_detail_view(request: HttpRequest, produit_id: int) -> HttpResponse:
    """Affiche la fiche d'un produit du catalogue."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    try:
        produit = ProduitsClient(request).get_product(produit_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Produit introuvable.")
        return redirect("catalogue")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("catalogue")
    except APIClientError:
        messages.error(request, "Erreur lors du chargement du produit.")
        return redirect("catalogue")

    # Résolution best-effort du libellé du taux de TVA (la fiche reste
    # affichable même si le référentiel est momentanément indisponible).
    taux_label = None
    try:
        taux_list = TauxTvaClient(request).list_taux()
        taux_label = next(
            (
                _format_taux_label(t)
                for t in taux_list
                if t.get("id") == produit.get("id_taux_tva")
            ),
            None,
        )
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        pass

    return render(
        request,
        "core/catalogue_detail.html",
        {"produit": produit, "taux_label": taux_label},
    )


def catalogue_update_view(request: HttpRequest, produit_id: int) -> HttpResponse:
    """Édite un produit du catalogue (formulaire pré-rempli, PATCH)."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = ProduitsClient(request)

    try:
        produit = client.get_product(produit_id)
        taux_choices = _load_taux_choices(request)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Produit introuvable.")
        return redirect("catalogue")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("catalogue")
    except APIClientError:
        messages.error(request, "Erreur lors du chargement du produit.")
        return redirect("catalogue")

    if request.method == "POST":
        form = CatalogueForm(request.POST, taux_choices=taux_choices, is_edit=True)
        if form.is_valid():
            try:
                client.update_product(produit_id, form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de la modification du produit.")
            else:
                messages.success(request, "Le produit a été modifié avec succès.")
                return redirect("catalogue_detail", produit_id=produit_id)
    else:
        form = CatalogueForm(initial=produit, taux_choices=taux_choices, is_edit=True)

    return render(
        request,
        "core/catalogue_form.html",
        {"form": form, "is_edit": True, "produit": produit},
    )


@require_POST
def catalogue_deactivate_view(request: HttpRequest, produit_id: int) -> HttpResponse:
    """Désactive un produit (soft delete via DELETE côté API)."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    try:
        ProduitsClient(request).delete_product(produit_id)
        messages.success(request, "Le produit a été désactivé.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Produit introuvable.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Désactivation refusée."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError:
        messages.error(request, "Erreur lors de la désactivation du produit.")

    return redirect("catalogue")
