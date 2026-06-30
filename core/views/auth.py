import httpx
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render

from clients.api_client import APIAuthClient


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        client = APIAuthClient()
        result = client.login(email, password)

        # 1. Si le login réussit et qu'on a un token
        if "access_token" in result:
            token = result["access_token"]
            auth_headers = {"Authorization": f"Bearer {token}"}

            # 2. Résolution de l'entreprise active (le tenant).
            #    L'auth /auth/token est GLOBALE : elle ne porte pas d'entreprise.
            #    On découvre les entreprises de l'utilisateur via /abonnements/me.
            #    Sans entreprise_id, toutes les routes métier (header
            #    x-entreprise-id requis) échoueraient.
            try:
                abonnements_resp = httpx.get(
                    f"{settings.API_DATA_URL}/abonnements/me",
                    headers=auth_headers,
                )
                abonnements_resp.raise_for_status()
                abonnements = abonnements_resp.json()
            except Exception:
                messages.error(
                    request, "Impossible de récupérer votre espace de travail."
                )
                return render(request, "core/login.html")

            if not abonnements:
                messages.error(
                    request,
                    "Aucun espace de travail n'est rattaché à votre compte.",
                )
                return render(request, "core/login.html")

            # MVP : on sélectionne la première entreprise rattachée.
            entreprise_id = abonnements[0].get("id_entreprise")

            request.session["is_authenticated"] = True
            request.session["jwt_token"] = token
            request.session["user_email"] = email
            request.session["entreprise_id"] = entreprise_id

            return redirect("home")

        # 3. Si le login a échoué (mauvais mot de passe, etc.)
        messages.error(
            request, result.get("error", "Erreur d'identifiants ou de connexion.")
        )

    # Affichage de la page de login (GET)
    return render(request, "core/login.html")


def logout_view(request):
    """Détruit la session Django pour déconnecter l'utilisateur."""
    request.session.flush()
    return redirect("login")
