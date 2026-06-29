from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
import httpx
from clients.api_client import APIAuthClient


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        client = APIAuthClient()
        result = client.login(email, password)

        # 1. Si le login réussit et qu'on a un token
        if "access_token" in result:
            request.session["is_authenticated"] = True
            request.session["jwt_token"] = result["access_token"]
            request.session["user_email"] = email
            request.session["entreprise_id"] = result.get("entreprise_id")

            # 2. Appel immédiat à /me pour récupérer le profil d'entreprise
            try:
                headers = {"Authorization": f"Bearer {result['access_token']}"}

                profil_response = httpx.get(
                    f"{settings.API_DATA_URL}/utilisateurs/me", headers=headers
                )
                profil_response.raise_for_status()
                _profil_data = profil_response.json()

                # Redirection vers l'accueil une fois le token et l'ID d'entreprise stockés
                return redirect("home")

            except Exception:
                # En cas d'échec de récupération du profil, on nettoie tout par sécurité
                request.session.flush()
                messages.error(
                    request, "Impossible de charger votre profil d'entreprise."
                )
                return render(request, "core/login.html")

        # 3. Si le login a échoué (mauvais mot de passe, etc.)
        else:
            messages.error(
                request, result.get("error", "Erreur d'identifiants ou de connexion.")
            )

    # Affichage de la page de login (GET)
    return render(request, "core/login.html")


def logout_view(request):
    """Détruit la session Django pour déconnecter l'utilisateur."""
    request.session.flush()
    return redirect("login")
