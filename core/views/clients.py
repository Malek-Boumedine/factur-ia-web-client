"""Vues du domaine clients (tiers facturés).

Liste (recherche, filtre actif/inactif, pagination — état porté par les query
params de l'URL), création (avec pré-remplissage via la recherche SIRENE),
détail, édition et désactivation (soft delete côté API). Tout appel réseau
passe par la couche `clients/`.
"""

import re

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from clients.clients_client import ClientsClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from core.forms import ClientForm
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


_SIRENE_INITIAL_FIELDS = (
    "raison_sociale",
    "siret",
    "numero_tva",
    "adresse",
    "code_postal",
    "ville",
)

# Rattachement des messages de conflit 409 aux champs du formulaire client :
# mot-clé (minuscule) recherché dans le message de l'API -> champ concerné.
_CONFLICT_FIELD_KEYWORDS = {
    "siret": "siret",
    "tva": "numero_tva",
}


def client_create_view(request: HttpRequest) -> HttpResponse:
    """Crée un client ; pré-remplissage optionnel via la recherche SIRENE.

    GET : formulaire vide, ou pré-rempli si un identifiant SIRET/SIREN est
    fourni en query param (`siret`). POST : validation puis création via l'API
    et redirection vers la fiche du client créé.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = ClientsClient(request)

    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            try:
                created = client.create_client(form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de la création du client.")
            else:
                messages.success(request, "Le client a été créé avec succès.")
                return redirect("client_detail", client_id=created["id"])
        return render(
            request, "core/client_form.html", {"form": form, "is_edit": False}
        )

    # GET : pré-remplissage éventuel via la recherche SIRENE.
    initial = {}
    sirene_query = request.GET.get("siret", "").strip()
    if sirene_query:
        if not re.fullmatch(r"\d{9}|\d{14}", sirene_query):
            messages.error(
                request,
                "Saisissez un SIREN (9 chiffres) ou un SIRET (14 chiffres).",
            )
        else:
            try:
                sirene = client.search_sirene(sirene_query)
                initial = {
                    field: sirene.get(field)
                    for field in _SIRENE_INITIAL_FIELDS
                    if sirene.get(field)
                }
                messages.success(
                    request,
                    "Informations trouvées : vérifiez et complétez le formulaire.",
                )
            except TokenExpiredError:
                return redirect("login")
            except ResourceNotFoundError:
                messages.error(
                    request, "Aucune entreprise trouvée pour cet identifiant."
                )
            except APIValidationError:
                messages.error(request, "Identifiant SIRET/SIREN invalide.")
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de la recherche SIRENE.")

    form = ClientForm(initial=initial)
    return render(
        request,
        "core/client_form.html",
        {"form": form, "is_edit": False, "sirene_query": sirene_query},
    )


def client_detail_view(request: HttpRequest, client_id: int) -> HttpResponse:
    """Affiche la fiche d'un client."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    try:
        client_data = ClientsClient(request).get_client(client_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Client introuvable.")
        return redirect("clients")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("clients")
    except APIClientError:
        messages.error(request, "Erreur lors du chargement du client.")
        return redirect("clients")

    return render(request, "core/client_detail.html", {"client": client_data})


def client_update_view(request: HttpRequest, client_id: int) -> HttpResponse:
    """Édite un client (formulaire pré-rempli, PATCH à la soumission)."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = ClientsClient(request)

    try:
        client_data = client.get_client(client_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Client introuvable.")
        return redirect("clients")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("clients")
    except APIClientError:
        messages.error(request, "Erreur lors du chargement du client.")
        return redirect("clients")

    if request.method == "POST":
        form = ClientForm(request.POST, is_edit=True)
        if form.is_valid():
            try:
                client.update_client(client_id, form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de la modification du client.")
            else:
                messages.success(request, "Le client a été modifié avec succès.")
                return redirect("client_detail", client_id=client_id)
    else:
        form = ClientForm(initial=client_data, is_edit=True)

    return render(
        request,
        "core/client_form.html",
        {"form": form, "is_edit": True, "client": client_data},
    )


@require_POST
def client_deactivate_view(request: HttpRequest, client_id: int) -> HttpResponse:
    """Désactive un client (soft delete via DELETE côté API)."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    try:
        ClientsClient(request).delete_client(client_id)
        messages.success(request, "Le client a été désactivé.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Client introuvable.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Désactivation refusée."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError:
        messages.error(request, "Erreur lors de la désactivation du client.")

    return redirect("clients")


@require_POST
def client_reactivate_view(request: HttpRequest, client_id: int) -> HttpResponse:
    """Réactive un client (PATCH est_actif=true côté API)."""
    if not request.session.get("is_authenticated"):
        return redirect("login")

    try:
        ClientsClient(request).update_client(client_id, {"est_actif": True})
        messages.success(request, "Le client a été réactivé.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Client introuvable.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Réactivation refusée."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError:
        messages.error(request, "Erreur lors de la réactivation du client.")

    return redirect("clients")
