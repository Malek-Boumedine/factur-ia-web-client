"""Vue « Modifier mes accès » (identifiants de connexion).

Page `/mes-acces/` regroupant les deux opérations sensibles du compte, isolées
de la page « Informations compte » pour qu'un changement d'identifiant soit
toujours une action délibérée (et jamais dupliquée sur deux écrans).

Deux sections indépendantes, chacune avec son formulaire et son endpoint,
distinguées par un champ caché `action` (pattern de la page équipe) :

- `email` : POST /utilisateurs/me/changer-email — l'email est le sujet du JWT,
  la réponse porte un nouveau token qui REMPLACE `jwt_token` en session (sinon
  401 au prochain appel), et `user_email` est resynchronisé (affichage header,
  masquage « propre ligne » de la page équipe) ;
- `mot_de_passe` : POST /utilisateurs/me/changer-mot-de-passe.

Les deux endpoints exigent le mot de passe actuel : aucun changement à
l'aveugle sur une session ouverte. Tout appel réseau passe par la couche
`clients/` (le navigateur ne joint jamais l'API directement) et les POST sont
protégés par CSRF.

Les 422 sont reportés dans les champs, le 409 (email pris) sur le champ email,
les 400 en message local fixe (le client de base ne conserve pas le `detail`
des 400) — l'API restant juge de vérité. Ces messages 400 recouvrent
volontairement les deux causes possibles sans dire laquelle s'applique : rien
ne doit permettre de sonder un mot de passe ou l'existence d'un email.
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
from core.forms import ChangementEmailForm, ChangementMotDePasseForm
from core.views.auth import _MSG_INDISPONIBLE, _appliquer_erreurs_api

# Messages fixes des 400, alignés sur les libellés du contrat (le corps des
# 400 n'est pas conservé par la couche cliente, contrairement aux 409/422).
_MSG_400_EMAIL = "Mot de passe actuel incorrect, ou nouvel email identique à l'actuel."
_MSG_400_MDP = (
    "Mot de passe actuel incorrect, ou nouveau mot de passe identique à l'actuel."
)


def acces_view(request: HttpRequest) -> HttpResponse:
    """Affiche et traite le changement d'email et de mot de passe (PRG).

    GET : deux formulaires vierges, l'email actuel affiché en lecture seule.
    POST : la section visée (`action`) est validée et envoyée à son endpoint ;
    en cas d'erreur, la page est ré-affichée avec le formulaire de la section
    lié, l'autre vierge. Les mots de passe saisis ne sont jamais réinjectés
    dans le HTML (les gabarits n'exposent pas leur `value`).
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = UtilisateursClient(request)

    # Email actuel : affiché en lecture seule au-dessus du formulaire. La
    # session suffit dans le cas courant ; l'appel API n'est fait que pour
    # afficher une valeur de référence à jour, et son échec n'empêche rien.
    current_email = request.session.get("user_email", "")
    try:
        profil = client.get_my_profile()
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        pass
    else:
        current_email = profil.get("email") or current_email

    form_email = ChangementEmailForm()
    form_mdp = ChangementMotDePasseForm()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "email":
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
                    return redirect("acces")

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
                    return redirect("acces")

    context = {
        "form_email": form_email,
        "form_mdp": form_mdp,
        "current_email": current_email,
    }
    return render(request, "core/acces.html", context)
