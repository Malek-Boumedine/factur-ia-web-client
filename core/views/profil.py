"""Vue « Informations compte » (identité de l'utilisateur et de son entreprise).

Page `/profil/` centrée sur les informations, sans opération sensible : le
changement d'email et de mot de passe vit sur sa propre page (`acces`, voir
`core/views/acces.py`) pour éviter tout doublon sur ces actions.

Trois blocs :

- « Mon compte » : synthèse en lecture seule issue de GET /utilisateurs/me
  (email de connexion, rôle dans l'entreprise, dernière connexion, date de
  création). Aucun appel supplémentaire — ces champs sont déjà dans la réponse
  qui sert au pré-remplissage du formulaire ;
- « Mon entreprise » : lecture seule (GET /entreprises/me), masquée pour un
  utilisateur sans entreprise active (admin plateforme pur) ;
- « Mes informations » : formulaire d'édition (PATCH /utilisateurs/me, schéma
  ProfilUpdate).

Tout appel réseau passe par la couche `clients/`. Les 422 sont reportés dans
les champs — l'API restant juge de vérité.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_datetime

from clients.entreprises_client import EntreprisesClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    TokenExpiredError,
)
from clients.utilisateurs_client import UtilisateursClient
from core.forms import ProfilForm
from core.views.auth import _MSG_INDISPONIBLE, _appliquer_erreurs_api

# Champs du profil pré-remplis depuis GET /utilisateurs/me (schéma ProfilUpdate).
_PROFIL_FIELDS = (
    "nom",
    "prenom",
    "adresse",
    "adresse_complement",
    "code_postal",
    "ville",
    "telephone",
)


def _parse_datetime(value):
    """Convertit un horodatage ISO de l'API en objet `datetime`.

    Best-effort : renvoie `None` si la valeur est absente ou inattendue, pour
    que l'affichage se dégrade proprement (ligne simplement omise).
    """
    if not value:
        return None
    try:
        return parse_datetime(str(value))
    except ValueError:
        return None


def profil_view(request: HttpRequest) -> HttpResponse:
    """Affiche les informations du compte et traite leur mise à jour.

    GET : pré-remplissage du formulaire depuis GET /utilisateurs/me, dont la
    réponse alimente aussi la synthèse en lecture seule. POST : mise à jour via
    PATCH /utilisateurs/me, puis redirection (PRG).
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = UtilisateursClient(request)

    # Profil courant : pré-remplissage du formulaire et synthèse « Mon compte ».
    # Best-effort : la page reste utilisable si l'appel échoue.
    profil: dict = {}
    try:
        profil = client.get_my_profile()
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError:
        messages.error(request, "Erreur lors du chargement du profil.")

    # Entreprise active : section « Mon entreprise » (lecture seule). Masquée
    # sans `entreprise_id` en session (admin plateforme pur) ; en cas d'échec,
    # alerte locale dans la section — pas de bannière globale, pour éviter le
    # doublon avec un éventuel échec du chargement du profil.
    entreprise: dict | None = None
    entreprise_error: str | None = None
    if request.session.get("entreprise_id"):
        try:
            entreprise = EntreprisesClient(request).get_my_entreprise()
        except TokenExpiredError:
            return redirect("login")
        except APIClientError:
            entreprise_error = _MSG_INDISPONIBLE

    form_infos = ProfilForm(initial={f: profil.get(f) for f in _PROFIL_FIELDS})

    if request.method == "POST":
        form_infos = ProfilForm(request.POST)
        if form_infos.is_valid():
            try:
                client.update_my_profile(form_infos.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except APIValidationError as e:
                _appliquer_erreurs_api(form_infos, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de la mise à jour du profil.")
            else:
                messages.success(request, "Vos informations ont été mises à jour.")
                return redirect("profil")

    context = {
        "form_infos": form_infos,
        "current_email": profil.get("email") or request.session.get("user_email", ""),
        # `role` n'est renseigné par l'API que dans le contexte d'une entreprise
        # (header tenant) : absent pour un admin plateforme pur.
        "role": profil.get("role"),
        "est_admin": profil.get("est_admin"),
        "date_derniere_connexion": _parse_datetime(
            profil.get("date_derniere_connexion")
        ),
        "date_creation": _parse_datetime(profil.get("date_creation")),
        "entreprise": entreprise,
        "entreprise_error": entreprise_error,
    }
    return render(request, "core/profil.html", context)
