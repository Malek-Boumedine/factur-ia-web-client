from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render

from clients.abonnements_client import AbonnementsClient
from clients.api_client import APIAuthClient
from clients.comptes_client import ComptesClient
from clients.entreprises_client import EntreprisesClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    TokenExpiredError,
)
from core.forms import (
    EntrepriseForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    SignUpForm,
)

# Libellé générique en cas d'indisponibilité de l'API (résilience réseau).
_MSG_INDISPONIBLE = "Service momentanément indisponible. Veuillez réessayer."


def _appliquer_erreurs_api(form, detail):
    """Reporte les erreurs 422 de l'API dans les champs du formulaire.

    Le `detail` FastAPI est soit une liste d'objets `{loc, msg}` (on rattache
    chaque message au champ correspondant), soit une chaîne (erreur globale).
    Les champs inconnus du formulaire retombent sur une erreur non liée.
    """
    if isinstance(detail, list):
        for item in detail:
            loc = item.get("loc") or [] if isinstance(item, dict) else []
            champ = loc[-1] if loc else None
            msg = item.get("msg") if isinstance(item, dict) else str(item)
            if champ in form.fields:
                form.add_error(champ, msg or "Valeur invalide.")
            else:
                form.add_error(None, msg or "Données invalides.")
    elif detail:
        form.add_error(None, str(detail))
    else:
        form.add_error(None, "Données invalides.")


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        result = APIAuthClient().login(email, password)

        # 1. Échec d'authentification (identifiants invalides, API injoignable) :
        #    APIAuthClient renvoie {"error": ...}, jamais d'exception.
        if "access_token" not in result:
            messages.error(
                request, result.get("error", "Erreur d'identifiants ou de connexion.")
            )
            return render(request, "core/auth/sign-in.html")

        # 2. On pose le JWT en session immédiatement : les appels métier qui
        #    suivent (résolution d'entreprise, onboarding) passent par la couche
        #    clients/, qui lit le token depuis la session. `entreprise_id` reste
        #    inconnu à ce stade et sera résolu juste après.
        request.session["is_authenticated"] = True
        request.session["jwt_token"] = result["access_token"]
        request.session["user_email"] = email

        # 3. Résolution des entreprises rattachées via /abonnements/me (la route
        #    /auth/token est globale et ne porte pas d'entreprise). Tout passe
        #    par clients/ : résilience réseau + mapping d'exceptions.
        try:
            abonnements = AbonnementsClient(request).get_my_subscription()
        except APIUnavailableError:
            request.session.flush()
            messages.error(request, _MSG_INDISPONIBLE)
            return render(request, "core/auth/sign-in.html")
        except APIClientError:
            request.session.flush()
            messages.error(request, "Impossible de récupérer votre espace de travail.")
            return render(request, "core/auth/sign-in.html")

        # 4. Aucune entreprise rattachée : on oriente vers l'onboarding plutôt
        #    que de bloquer (la session porte déjà le JWT nécessaire).
        if not abonnements:
            return redirect("onboarding")

        # 5. MVP : on sélectionne la première entreprise rattachée.
        request.session["entreprise_id"] = abonnements[0].get("id_entreprise")
        return redirect("home")

    # Affichage de la page de connexion (GET)
    return render(request, "core/auth/sign-in.html")


def logout_view(request):
    """Détruit la session Django pour déconnecter l'utilisateur."""
    request.session.flush()
    return redirect("login")


def signup_view(request):
    """Inscription publique (POST /utilisateurs/inscription).

    L'API ne renvoie pas de token : en cas de succès, on redirige vers la
    connexion avec un message. Le rôle est injecté depuis les settings
    (aucun sélecteur public, /auth/roles exigeant une authentification).
    """
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            payload = form.to_api_payload(
                id_role=settings.SIGNUP_DEFAULT_ROLE_ID, est_admin=True
            )
            try:
                ComptesClient(request).register(payload)
                messages.success(
                    request,
                    "Votre compte a été créé. Vous pouvez maintenant vous connecter.",
                )
                return redirect("login")
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Erreur lors de la création du compte.")
        return render(request, "core/auth/sign-up.html", {"form": form})

    return render(request, "core/auth/sign-up.html", {"form": SignUpForm()})


def forgot_password_view(request):
    """Demande de réinitialisation (POST /auth/mot-de-passe-oublie).

    Comportement neutre : après une soumission valide, on affiche toujours le
    même message, que le compte existe ou non (ne pas divulguer l'existence).
    """
    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            try:
                ComptesClient(request).forgot_password(form.cleaned_data["email"])
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
                return render(request, "core/auth/forgot-password.html", {"form": form})
            except APIClientError:
                # On reste neutre : ne pas révéler la cause d'un éventuel échec.
                pass
            return render(request, "core/auth/forgot-password.html", {"envoye": True})
        return render(request, "core/auth/forgot-password.html", {"form": form})

    return render(
        request, "core/auth/forgot-password.html", {"form": ForgotPasswordForm()}
    )


def reset_password_view(request):
    """Réinitialisation du mot de passe (POST /auth/reinitialiser-mot-de-passe).

    Le token provient du lien email, transmis en paramètre d'URL (`?token=`)
    puis conservé dans un champ caché du formulaire. Un token absent affiche un
    message d'erreur clair ; un token invalide/expiré est signalé via l'API.
    """
    if request.method == "POST":
        token = request.POST.get("token", "")
        form = ResetPasswordForm(request.POST)
        if not token:
            messages.error(request, "Lien de réinitialisation invalide ou expiré.")
        elif form.is_valid():
            try:
                ComptesClient(request).reset_password(
                    token, form.cleaned_data["nouveau_mot_de_passe"]
                )
                messages.success(
                    request,
                    "Votre mot de passe a été réinitialisé. Vous pouvez vous connecter.",
                )
                return redirect("login")
            except APIValidationError as e:
                # Token invalide/expiré ou mot de passe refusé par l'API.
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Impossible de réinitialiser le mot de passe.")
        return render(
            request, "core/auth/reset-password.html", {"form": form, "token": token}
        )

    token = request.GET.get("token", "")
    if not token:
        messages.error(request, "Lien de réinitialisation invalide ou expiré.")
    return render(
        request,
        "core/auth/reset-password.html",
        {"form": ResetPasswordForm(), "token": token},
    )


def profile_lock_view(request):
    """Maquette visuelle « écran verrouillé » (aucune route API).

    Page en attente : le template n'est relié à aucun endpoint. Fournie pour
    prévisualisation, à brancher ultérieurement.
    """
    return render(request, "core/auth/profile-lock.html")


def onboarding_view(request):
    """Création du premier espace de travail (POST /entreprises/).

    Écran présenté après login quand l'utilisateur n'a aucune entreprise
    rattachée. Le JWT est déjà en session (posé par `login_view`) : le client
    entreprises le réutilise, sans `x-entreprise-id` (pas encore d'entreprise).
    Après création, on initialise `entreprise_id` en session et on donne accès
    à l'application.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")
    # Déjà un espace de travail : rien à créer, on renvoie vers l'app.
    if request.session.get("entreprise_id"):
        return redirect("home")

    if request.method == "POST":
        form = EntrepriseForm(request.POST)
        if form.is_valid():
            try:
                entreprise = EntreprisesClient(request).create_entreprise(
                    form.to_api_payload()
                )
                request.session["entreprise_id"] = entreprise["id"]
                messages.success(
                    request, "Votre espace de travail a été créé avec succès."
                )
                return redirect("home")
            except TokenExpiredError:
                return redirect("login")
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Impossible de créer l'espace de travail.")
        return render(request, "core/onboarding.html", {"form": form})

    return render(request, "core/onboarding.html", {"form": EntrepriseForm()})
