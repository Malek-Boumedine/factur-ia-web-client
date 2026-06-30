import httpx
from django.contrib import messages
from django.shortcuts import redirect, render

from clients.base_client import TokenExpiredError
from clients.utilisateurs_client import UtilisateursClient
from core.forms import CollaborateurForm


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
            except httpx.HTTPStatusError as e:
                messages.error(
                    request,
                    f"Erreur lors de la suppression ({e.response.status_code}).",
                )
            return redirect("equipe")

        # Ajout / modification : validation serveur via le formulaire.
        try:
            roles, _ = _charger_roles(client)
        except TokenExpiredError:
            return redirect("login")
        except httpx.HTTPStatusError:
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
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", "Erreur de validation.")
                except ValueError:
                    detail = "Erreur de validation."
                messages.error(request, str(detail))

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
    """Charge la liste des membres (avec id_role résolu) et les rôles."""
    membres = []
    roles = []
    role_map = {}

    # TokenExpiredError n'est pas un HTTPStatusError : il se propage et est
    # traité par l'appelant (redirection vers /login).
    try:
        roles, role_map = _charger_roles(client)
    except httpx.HTTPStatusError:
        messages.error(request, "Impossible de charger la liste des rôles.")

    try:
        membres = client.get_equipe()
        # L'API renvoie le libellé du rôle (pas l'id) : on résout l'id_role
        # pour pouvoir pré-remplir le menu déroulant à l'édition.
        for membre in membres:
            membre["id_role"] = role_map.get(membre.get("role"))
    except httpx.HTTPStatusError:
        messages.error(request, "Impossible de charger la liste des membres.")

    return {"membres": membres, "roles": roles}
