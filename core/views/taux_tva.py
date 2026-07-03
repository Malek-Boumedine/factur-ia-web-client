"""Vues d'administration des taux de TVA (données de référence globales).

Réservées aux administrateurs de la plateforme (garde-fou de session
`is_platform_admin`, l'API restant juge de vérité — un 403 est traité comme un
accès refusé). Couvre la liste (avec filtre actif/inactif), la création,
l'édition et la (dés)activation en soft delete :

- désactivation = DELETE /taux-tva/{id} (l'API bascule `est_actif=False`) ;
- réactivation = PATCH /taux-tva/{id} avec `est_actif=True`.

Le formulaire ne gère que `taux`, `libelle` et `code_comptable` ; la
(dés)activation passe uniquement par les actions de la liste. Tout appel réseau
passe par la couche `clients/`.
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
from clients.taux_tva_client import TauxTvaClient
from core.forms import TauxTvaForm
from core.pagination import parse_bool_filter
from core.views.abonnements import _guard_platform_admin, _refus_api
from core.views.auth import (
    _MSG_INDISPONIBLE,
    _appliquer_erreur_conflit,
    _appliquer_erreurs_api,
)

# Rattachement du message de conflit 409 (taux déjà existant, valeur unique)
# au champ concerné du formulaire.
_CONFLICT_FIELD_KEYWORDS = {"taux": "taux"}


def _format_taux(value) -> str:
    """Formate un taux en pourcentage à la française (ex. « 20 », « 5,5 »).

    La valeur arrive en chaîne décimale (ex. "20.00") : on retire les zéros non
    significatifs et on affiche la virgule décimale française.
    """
    try:
        formatted = format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, TypeError):
        return str(value)
    return formatted.replace(".", ",")


def _with_display_taux(taux_list: list) -> list:
    """Enrichit chaque taux d'un champ d'affichage `taux_affiche`."""
    for taux in taux_list:
        taux["taux_affiche"] = _format_taux(taux.get("taux"))
    return taux_list


def taux_tva_admin_view(request: HttpRequest) -> HttpResponse:
    """Liste les taux de TVA avec les actions de gestion (admin plateforme)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    est_actif_raw = request.GET.get("est_actif", "")
    est_actif = parse_bool_filter(est_actif_raw)

    taux_list: list = []
    try:
        taux_list = _with_display_taux(
            TauxTvaClient(request).list_taux(est_actif=est_actif)
        )
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Impossible de charger la liste des taux de TVA.")

    return render(
        request,
        "core/taux_tva_admin.html",
        {"taux_list": taux_list, "est_actif": est_actif_raw},
    )


def taux_tva_create_view(request: HttpRequest) -> HttpResponse:
    """Crée un taux de TVA (admin plateforme)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    if request.method == "POST":
        form = TauxTvaForm(request.POST)
        if form.is_valid():
            try:
                TauxTvaClient(request).create_taux(form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError as e:
                if e.status_code == 403:
                    return _refus_api(request)
                messages.error(request, "Erreur lors de la création du taux de TVA.")
            else:
                messages.success(request, "Le taux de TVA a été créé avec succès.")
                return redirect("taux_tva_admin")
    else:
        form = TauxTvaForm()

    return render(request, "core/taux_tva_form.html", {"form": form, "is_edit": False})


def taux_tva_update_view(request: HttpRequest, taux_tva_id: int) -> HttpResponse:
    """Édite un taux de TVA (formulaire pré-rempli, PATCH)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    client = TauxTvaClient(request)

    try:
        taux = client.get_taux(taux_tva_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Taux de TVA introuvable.")
        return redirect("taux_tva_admin")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("taux_tva_admin")
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Erreur lors du chargement du taux de TVA.")
        return redirect("taux_tva_admin")

    if request.method == "POST":
        form = TauxTvaForm(request.POST, is_edit=True)
        if form.is_valid():
            try:
                client.update_taux(taux_tva_id, form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except ResourceNotFoundError:
                messages.error(request, "Taux de TVA introuvable.")
                return redirect("taux_tva_admin")
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError as e:
                if e.status_code == 403:
                    return _refus_api(request)
                messages.error(
                    request, "Erreur lors de la modification du taux de TVA."
                )
            else:
                messages.success(request, "Le taux de TVA a été modifié avec succès.")
                return redirect("taux_tva_admin")
    else:
        form = TauxTvaForm(initial=taux, is_edit=True)

    return render(
        request,
        "core/taux_tva_form.html",
        {"form": form, "is_edit": True, "taux": taux},
    )


@require_POST
def taux_tva_deactivate_view(request: HttpRequest, taux_tva_id: int) -> HttpResponse:
    """Désactive un taux de TVA (soft delete via DELETE côté API)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        TauxTvaClient(request).deactivate_taux(taux_tva_id)
        messages.success(request, "Le taux de TVA a été désactivé.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Taux de TVA introuvable.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Désactivation refusée."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Erreur lors de la désactivation du taux de TVA.")

    return redirect("taux_tva_admin")


@require_POST
def taux_tva_reactivate_view(request: HttpRequest, taux_tva_id: int) -> HttpResponse:
    """Réactive un taux de TVA (PATCH est_actif=true côté API)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        TauxTvaClient(request).update_taux(taux_tva_id, {"est_actif": True})
        messages.success(request, "Le taux de TVA a été réactivé.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Taux de TVA introuvable.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Réactivation refusée."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Erreur lors de la réactivation du taux de TVA.")

    return redirect("taux_tva_admin")
