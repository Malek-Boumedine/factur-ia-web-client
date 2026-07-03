from django.contrib import messages
from django.shortcuts import redirect, render

from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from clients.utilisateurs_client import UtilisateursClient
from core.forms import CollaborateurForm
from core.views.auth import _MSG_INDISPONIBLE

# Message affiché sur le 403 du DELETE : le contrat n'expose pas le flag
# `compte_protege` dans UtilisateurRead, l'UI ne peut donc pas masquer le
# bouton préventivement — l'API reste juge et on traduit son refus.
_MSG_COMPTE_PROTEGE = "Ce compte est protégé et ne peut pas être supprimé."


def _charger_roles(client):
    """Récupère les rôles et construit la table libellé -> id."""
    roles = client.get_roles()
    role_map = {r.get("libelle"): r.get("id") for r in roles}
    return roles, role_map


def equipe_view(request):
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = UtilisateursClient(request)

    if request.method == "POST":
        action = request.POST.get("action", "add")
        user_id = request.POST.get("user_id")

        if action == "delete":
            try:
                client.delete_utilisateur(user_id)
                messages.success(
                    request, "Le collaborateur a été supprimé avec succès."
                )
            except TokenExpiredError:
                return redirect("login")
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError as e:
                if e.status_code == 403:
                    messages.error(request, _MSG_COMPTE_PROTEGE)
                else:
                    messages.error(
                        request,
                        f"Erreur lors de la suppression ({e.status_code}).",
                    )
            return redirect("equipe")

        # Désactivation / réactivation : PATCH sur `est_actif` uniquement.
        # La réactivation peut être refusée en 409 si la limite d'utilisateurs
        # du plan actif est atteinte : le message actionnable de l'API est
        # affiché tel quel.
        if action in ("deactivate", "reactivate"):
            est_actif = action == "reactivate"
            try:
                client.update_utilisateur(user_id, {"est_actif": est_actif})
                messages.success(
                    request,
                    "Le collaborateur a été réactivé."
                    if est_actif
                    else "Le collaborateur a été désactivé.",
                )
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                messages.error(
                    request,
                    str(
                        e.detail
                        or "La limite d'utilisateurs de votre plan est atteinte."
                    ),
                )
            except ResourceNotFoundError:
                messages.error(request, "Collaborateur introuvable.")
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(
                    request,
                    "Erreur lors de la réactivation."
                    if est_actif
                    else "Erreur lors de la désactivation.",
                )
            return redirect("equipe")

        # Ajout / modification : validation serveur via le formulaire.
        try:
            roles, _ = _charger_roles(client)
        except TokenExpiredError:
            return redirect("login")
        except APIClientError:
            roles = []

        is_create = action != "edit"
        form = CollaborateurForm(
            request.POST,
            is_create=is_create,
            role_ids=[r.get("id") for r in roles],
        )

        if form.is_valid():
            payload = form.to_api_payload()
            try:
                if not is_create and user_id:
                    client.update_utilisateur(user_id, payload)
                    messages.success(request, "Le collaborateur a bien été modifié.")
                else:
                    client.inviter_utilisateur(payload)
                    messages.success(
                        request,
                        f"L'utilisateur {payload['email']} a bien été ajouté.",
                    )
                return redirect("equipe")
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                # Limite d'utilisateurs du plan atteinte (ajout ou réactivation) :
                # le message de l'API est actionnable, on l'affiche tel quel.
                messages.error(
                    request,
                    str(
                        e.detail
                        or "La limite d'utilisateurs de votre plan est atteinte."
                    ),
                )
            except APIValidationError as e:
                messages.error(request, str(e.detail or "Erreur de validation."))
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de l'enregistrement.")

        # Formulaire invalide (ou erreur API) : on ré-affiche la page avec la
        # modale ouverte, les valeurs saisies et les erreurs de champ.
        try:
            contexte = _contexte_liste(request, client)
        except TokenExpiredError:
            return redirect("login")
        return render(
            request,
            "core/equipe.html",
            {
                **contexte,
                "form": form,
                "open_modal": True,
                "form_action": "edit" if not is_create else "add",
                "edit_user_id": user_id or "",
            },
        )

    try:
        contexte = _contexte_liste(request, client)
    except TokenExpiredError:
        return redirect("login")
    return render(request, "core/equipe.html", contexte)


def _contexte_liste(request, client):
    """Charge la liste des membres (avec id_role résolu) et les rôles.

    Fournit aussi `current_user_email` (session) : le template masque les
    actions incohérentes sur sa propre ligne (se désactiver, se supprimer).
    """
    membres = []
    roles = []
    role_map = {}

    # On laisse TokenExpiredError se propager (traité par l'appelant :
    # redirection vers /login) ; on n'intercepte que les autres erreurs API.
    try:
        roles, role_map = _charger_roles(client)
    except TokenExpiredError:
        raise
    except APIClientError:
        messages.error(request, "Impossible de charger la liste des rôles.")

    try:
        membres = client.get_equipe()
        # L'API renvoie le libellé du rôle (pas l'id) : on résout l'id_role
        # pour pouvoir pré-remplir le menu déroulant à l'édition.
        for membre in membres:
            membre["id_role"] = role_map.get(membre.get("role"))
    except TokenExpiredError:
        raise
    except APIClientError:
        messages.error(request, "Impossible de charger la liste des membres.")

    return {
        "membres": membres,
        "roles": roles,
        "current_user_email": request.session.get("user_email", ""),
    }
