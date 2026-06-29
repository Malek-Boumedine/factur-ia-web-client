from django.shortcuts import render, redirect
from django.contrib import messages
import httpx
from clients.utilisateurs_client import UtilisateursClient
from clients.base_client import TokenExpiredError


def equipe_view(request):
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = UtilisateursClient(request)

    if request.method == "POST":
        # Récupération des données du formulaire
        user_data = {
            "nom": request.POST.get("nom"),
            "prenom": request.POST.get("prenom"),
            "email": request.POST.get("email"),
            "password": request.POST.get("password"),
        }

        try:
            client.inviter_utilisateur(user_data)
            messages.success(
                request, f"L'utilisateur {user_data['email']} a bien été ajouté."
            )
        except TokenExpiredError:
            return redirect("login")

        except httpx.HTTPStatusError as e:
            # Si c'est une erreur de validation Pydantic (422)
            if e.response.status_code == 422:
                erreurs = e.response.json().get("detail", [])
                if isinstance(erreurs, list):
                    for err in erreurs:
                        # On récupère le nom du champ qui pose problème (ex: 'password')
                        champ = err.get("loc", [""])[-1]
                        # On traduit les messages Pydantic courants en français
                        if err.get("type") == "string_too_short":
                            msg = f"doit contenir au moins {err.get('ctx', {}).get('min_length')} caractères."
                        else:
                            msg = "est invalide."

                        messages.error(request, f"Le champ '{champ}' {msg}")
                else:
                    messages.error(request, "Données invalides fournies.")

            # Pour les autres erreurs (400, 403...)
            else:
                try:
                    error_detail = e.response.json().get(
                        "detail", "Erreur lors de la création."
                    )
                    # Si c'est une simple chaîne (ex: detail: "Email déjà utilisé")
                    if isinstance(error_detail, str):
                        messages.error(request, error_detail)
                    else:
                        messages.error(
                            request, f"Erreur serveur : {e.response.status_code}"
                        )
                except ValueError:
                    messages.error(
                        request, f"Erreur serveur : {e.response.status_code}"
                    )

        return redirect("equipe")

    membres = []
    try:
        membres = client.get_equipe()
    except TokenExpiredError:
        return redirect("login")
    except httpx.HTTPStatusError:
        messages.error(request, "Impossible de charger la liste des membres.")

    return render(request, "core/equipe.html", {"membres": membres})
