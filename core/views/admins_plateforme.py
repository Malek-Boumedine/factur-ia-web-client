"""Vue de gestion des administrateurs de plateforme.

Pages réservées aux administrateurs de plateforme : lister les admins, en
promouvoir de nouveaux (via recherche par email) et en révoquer. L'accès est
gardé par le flag de session `is_platform_admin` (posé au login), l'API restant
juge de vérité (un 403 est traité comme un accès refusé). Tout appel réseau
passe par la couche `clients/`.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.admins_plateforme_client import AdminsPlateformeClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    TokenExpiredError,
)
from core.views.auth import _MSG_INDISPONIBLE

# Message d'accès refusé (non-admin ou 403 renvoyé par l'API).
_MSG_ACCES_REFUSE = "Accès réservé aux administrateurs de la plateforme."

# Longueur minimale du fragment d'email exigée par l'API pour la recherche.
_EMAIL_SEARCH_MIN = 2


def admins_plateforme_view(request: HttpRequest) -> HttpResponse:
    """Liste les admins plateforme et gère promotion/révocation.

    GET : affiche la liste des admins et, si un fragment d'email est fourni, les
    résultats de recherche d'utilisateurs à promouvoir. POST : exécute une
    action (`promote`/`revoke`) puis redirige (POST-redirect-GET).
    """
    # Garde-fou d'accès : seul un admin plateforme entre ici.
    if not request.session.get("is_authenticated"):
        return redirect("login")
    if not request.session.get("is_platform_admin"):
        messages.error(request, _MSG_ACCES_REFUSE)
        return redirect("home")

    client = AdminsPlateformeClient(request)

    if request.method == "POST":
        return _handle_action(request, client)

    return _render_liste(request, client)


def _handle_action(
    request: HttpRequest, client: AdminsPlateformeClient
) -> HttpResponse:
    """Exécute une action de promotion ou de révocation, puis redirige."""
    action = request.POST.get("action")
    utilisateur_id = _parse_id(request.POST.get("utilisateur_id"))

    if action not in ("promote", "revoke") or utilisateur_id is None:
        messages.error(request, "Action invalide.")
        return redirect("admins_plateforme")

    try:
        if action == "promote":
            client.promote_admin(utilisateur_id)
            messages.success(
                request, "L'utilisateur a été promu administrateur de plateforme."
            )
        else:
            client.revoke_admin(utilisateur_id)
            messages.success(
                request, "Les droits d'administrateur de plateforme ont été révoqués."
            )
    except TokenExpiredError:
        return redirect("login")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Action refusée par le serveur."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            messages.error(request, _MSG_ACCES_REFUSE)
            return redirect("home")
        messages.error(request, "Erreur lors de l'exécution de l'action.")

    return redirect("admins_plateforme")


def _render_liste(request: HttpRequest, client: AdminsPlateformeClient) -> HttpResponse:
    """Charge la liste des admins et, le cas échéant, la recherche de promotion."""
    email_query = request.GET.get("email", "").strip()

    admins: list = []
    try:
        admins = client.list_admins()
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            # Flag de session obsolète : l'API fait autorité.
            messages.error(request, _MSG_ACCES_REFUSE)
            return redirect("home")
        messages.error(request, "Impossible de charger la liste des administrateurs.")

    # Recherche d'utilisateurs à promouvoir (uniquement si un email est saisi).
    search_results = None
    if email_query:
        if len(email_query) < _EMAIL_SEARCH_MIN:
            messages.info(
                request, "Saisissez au moins 2 caractères pour rechercher un email."
            )
        else:
            try:
                search_results = client.search_user_by_email(email_query)
            except TokenExpiredError:
                return redirect("login")
            except APIValidationError as e:
                messages.error(request, str(e.detail or "Recherche invalide."))
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError as e:
                if e.status_code == 403:
                    messages.error(request, _MSG_ACCES_REFUSE)
                    return redirect("home")
                messages.error(request, "Erreur lors de la recherche d'utilisateurs.")

    context = {
        "admins": admins,
        "email_query": email_query,
        "search_results": search_results,
        "current_user_email": request.session.get("user_email", ""),
    }
    return render(request, "core/admins.html", context)


def _parse_id(raw: str | None) -> int | None:
    """Convertit un identifiant brut de formulaire en entier, ou None si invalide."""
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
