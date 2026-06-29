from django.contrib import messages
from django.shortcuts import redirect, render
import httpx

from clients.base_client import TokenExpiredError
from clients.utilisateurs_client import UtilisateursClient


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

        user_data = {
            "nom": request.POST.get("nom"),
            "prenom": request.POST.get("prenom"),
            "email": request.POST.get("email"),
            "password": request.POST.get("password"),
            "id_role": request.POST.get("id_role"),
            "est_admin": request.POST.get("est_admin") == "on",
            "adresse": request.POST.get("adresse", "") or "Adresse non renseignée",
            "adresse_complement": request.POST.get("adresse_complement", ""),
            "code_postal": request.POST.get("code_postal", "") or "00000",
            "ville": request.POST.get("ville", "") or "Ville non renseignée",
            "telephone": request.POST.get("telephone", ""),
            "est_actif": True,
        }

        try:
            if action == "edit" and user_id:
                client.update_utilisateur(user_id, user_data)
                messages.success(request, "Le collaborateur a bien été modifié.")
            else:
                client.inviter_utilisateur(user_data)
                messages.success(
                    request,
                    f"L'utilisateur {user_data['email']} a bien été ajouté.",
                )
        except TokenExpiredError:
            return redirect("login")
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get("detail", "Erreur de validation.")
            except ValueError:
                detail = "Erreur de validation."
            messages.error(request, str(detail))

        return redirect("equipe")

    membres = []
    roles = []

    try:
        membres = client.get_equipe()
    except TokenExpiredError:
        return redirect("login")
    except httpx.HTTPStatusError:
        messages.error(request, "Impossible de charger la liste des membres.")

    try:
        roles = client.get_roles()
    except TokenExpiredError:
        return redirect("login")
    except httpx.HTTPStatusError:
        messages.error(request, "Impossible de charger la liste des rôles.")

    return render(
        request,
        "core/equipe.html",
        {
            "membres": membres,
            "roles": roles,
        },
    )
