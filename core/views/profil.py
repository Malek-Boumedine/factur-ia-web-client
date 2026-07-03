"""Vue du profil utilisateur (« Modifier mes informations »).

Une seule page (`/profil/`) portant trois sections indépendantes, chacune avec
son formulaire et son endpoint, distinguées par un champ caché `action`
(pattern de la page équipe) :

- `infos` : PATCH /utilisateurs/me (schéma ProfilUpdate) ;
- `email` : POST /utilisateurs/me/changer-email — l'email est le sujet du JWT,
  la réponse porte un nouveau token qui REMPLACE `jwt_token` en session (sinon
  401 au prochain appel), et `user_email` est resynchronisé (affichage header,
  masquage « propre ligne » de la page équipe) ;
- `mot_de_passe` : POST /utilisateurs/me/changer-mot-de-passe.

Tout appel réseau passe par la couche `clients/`. Les 422 sont reportés dans
les champs, le 409 (email pris) sur le champ email, les 400 en message local
fixe (le client de base ne conserve pas le `detail` des 400) — l'API restant
juge de vérité.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    TokenExpiredError,
)
from clients.utilisateurs_client import UtilisateursClient
from core.forms import ChangementEmailForm, ChangementMotDePasseForm, ProfilForm
from core.views.auth import _MSG_INDISPONIBLE, _appliquer_erreurs_api

# Messages fixes des 400, alignés sur les libellés du contrat (le corps des
# 400 n'est pas conservé par la couche cliente, contrairement aux 409/422).
_MSG_400_EMAIL = "Mot de passe actuel incorrect, ou nouvel email identique à l'actuel."
_MSG_400_MDP = (
    "Mot de passe actuel incorrect, ou nouveau mot de passe identique à l'actuel."
)

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


def profil_view(request: HttpRequest) -> HttpResponse:
    """Affiche et traite les trois sections du profil (PRG section par section).

    GET : pré-remplissage depuis GET /utilisateurs/me. POST : la section visée
    (`action`) est validée et envoyée à son endpoint ; en cas d'erreur, la page
    est ré-affichée avec le formulaire de la section lié, les autres vierges.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = UtilisateursClient(request)

    # Profil courant : pré-remplissage de « Mes informations » et affichage de
    # l'email actuel. Best-effort : la page reste utilisable si l'appel échoue.
    profil: dict = {}
    try:
        profil = client.get_my_profile()
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError:
        messages.error(request, "Erreur lors du chargement du profil.")

    form_infos = ProfilForm(initial={f: profil.get(f) for f in _PROFIL_FIELDS})
    form_email = ChangementEmailForm()
    form_mdp = ChangementMotDePasseForm()

    if request.method == "POST":
        action = request.POST.get("action", "infos")

        if action == "infos":
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

        elif action == "email":
            form_email = ChangementEmailForm(request.POST)
            if form_email.is_valid():
                cd = form_email.cleaned_data
                try:
                    result = client.change_my_email(
                        cd["mot_de_passe_actuel"], cd["nouvel_email"]
                    )
                except TokenExpiredError:
                    return redirect("login")
                except ResourceConflictError as e:
                    form_email.add_error(
                        "nouvel_email",
                        str(e.detail or "Cet email est déjà utilisé."),
                    )
                except APIValidationError as e:
                    _appliquer_erreurs_api(form_email, e.detail)
                except APIUnavailableError:
                    messages.error(request, _MSG_INDISPONIBLE)
                except APIClientError as e:
                    if e.status_code == 400:
                        form_email.add_error("mot_de_passe_actuel", _MSG_400_EMAIL)
                    else:
                        messages.error(request, "Erreur lors du changement d'email.")
                else:
                    # L'email est le sujet du JWT : l'ancien token est caduc,
                    # on le remplace AVANT le PRG et on resynchronise
                    # `user_email` (header, page équipe).
                    new_token = (
                        result.get("access_token") if isinstance(result, dict) else None
                    )
                    if not new_token:
                        # Filet hors contrat : sans token neuf, la session ne
                        # peut plus appeler l'API — reconnexion propre.
                        request.session.flush()
                        messages.error(
                            request,
                            "Votre email a été modifié : veuillez vous reconnecter.",
                        )
                        return redirect("login")
                    request.session["jwt_token"] = new_token
                    request.session["user_email"] = cd["nouvel_email"]
                    messages.success(request, "Votre email a été modifié.")
                    return redirect("profil")

        elif action == "mot_de_passe":
            form_mdp = ChangementMotDePasseForm(request.POST)
            if form_mdp.is_valid():
                cd = form_mdp.cleaned_data
                try:
                    client.change_my_password(
                        cd["mot_de_passe_actuel"], cd["nouveau_mot_de_passe"]
                    )
                except TokenExpiredError:
                    return redirect("login")
                except APIValidationError as e:
                    _appliquer_erreurs_api(form_mdp, e.detail)
                except APIUnavailableError:
                    messages.error(request, _MSG_INDISPONIBLE)
                except APIClientError as e:
                    if e.status_code == 400:
                        form_mdp.add_error("mot_de_passe_actuel", _MSG_400_MDP)
                    else:
                        messages.error(
                            request, "Erreur lors du changement de mot de passe."
                        )
                else:
                    messages.success(request, "Votre mot de passe a été modifié.")
                    return redirect("profil")

    context = {
        "form_infos": form_infos,
        "form_email": form_email,
        "form_mdp": form_mdp,
        "current_email": profil.get("email") or request.session.get("user_email", ""),
    }
    return render(request, "core/profil.html", context)
