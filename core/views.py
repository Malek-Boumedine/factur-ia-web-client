from django.shortcuts import render, redirect
from django.contrib import messages
from clients.api_client import APIAuthClient


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        client = APIAuthClient()
        result = client.login(email, password)

        if "access_token" in result:
            # Sécurisation du token dans la session côté serveur (Redis)
            request.session["jwt_token"] = result["access_token"]
            request.session["user_email"] = email
            request.session["is_authenticated"] = True

            return redirect("home")
        else:
            messages.error(request, result.get("error", "Erreur de connexion"))

    return render(request, "core/login.html")


def logout_view(request):
    """Détruit la session Django pour déconnecter l'utilisateur."""
    request.session.flush()
    return redirect("login")
