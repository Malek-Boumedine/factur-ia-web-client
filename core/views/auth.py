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
from clients.utilisateurs_client import UtilisateursClient
from core.forms import (
    EntrepriseForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    SignUpForm,
)

# Libellé générique en cas d'indisponibilité de l'API (résilience réseau).
_MSG_INDISPONIBLE = "Service momentanément indisponible. Veuillez réessayer."

# Message affiché à un admin plateforme sans entreprise qui accède à une page
# métier d'entreprise (voir `_guard_entreprise`).
_MSG_PAGE_ENTREPRISE = (
    "Cette page concerne un espace de travail entreprise. "
    "Votre compte administrateur de plateforme n'y est pas rattaché."
)

# Message affiché à un admin plateforme sans entreprise qui accède à
# l'onboarding : il gère la plateforme, pas un espace de travail client.
_MSG_ONBOARDING_ADMIN = (
    "En tant qu'administrateur de la plateforme, vous n'avez pas "
    "d'espace de travail entreprise à créer."
)

# Rôles d'entreprise autorisés à gérer l'équipe, alignés sur la permission
# `users:read` du seed API (attribuée au seul rôle PROPRIETAIRE). Seul endroit
# à ajuster si le mapping permission/rôle évolue côté API.
_TEAM_MANAGEMENT_ROLES = {"PROPRIETAIRE"}


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


def _appliquer_erreur_conflit(form, detail, field_keywords):
    """Reporte l'erreur de conflit 409 de l'API dans le formulaire.

    Le corps 409 est un message libre nommant la donnée en conflit (ex. « Un
    client avec ce SIRET existe déjà. ») : on le rattache au champ concerné en
    cherchant un mot-clé dans le message, sinon en erreur globale.

    Args:
        form: Formulaire Django cible.
        detail: Message de conflit renvoyé par l'API (champ `detail`).
        field_keywords (dict[str, str]): Mapping mot-clé (minuscule) -> nom du
            champ du formulaire (ex. `{"siret": "siret", "tva": "numero_tva"}`).
    """
    msg = str(detail or "Cette valeur est déjà utilisée.")
    lowered = msg.lower()
    for keyword, field in field_keywords.items():
        if keyword in lowered and field in form.fields:
            form.add_error(field, msg)
            return
    form.add_error(None, msg)


def _charger_flags_admin(request):
    """Renseigne en session les statuts admin et le droit de gérer l'équipe.

    Appelle GET /utilisateurs/me : le header `x-entreprise-id` est injecté
    automatiquement par la couche clients si une entreprise active est déjà
    en session, auquel cas l'API renseigne `est_admin` et `role` pour cette
    entreprise (sinon ils restent nuls). `can_manage_team` dérive du rôle
    (voir `_TEAM_MANAGEMENT_ROLES`), aligné sur la permission `users:read`
    de l'API. Cet enrichissement ne doit JAMAIS bloquer la connexion : en
    cas d'échec, les flags retombent à `False` (les liens et actions
    réservés seront simplement masqués).
    """
    try:
        profile = UtilisateursClient(request).get_my_profile()
    except APIClientError:
        profile = {}
    request.session["is_platform_admin"] = bool(profile.get("admin_plateforme"))
    request.session["is_entreprise_admin"] = bool(profile.get("est_admin"))
    request.session["can_manage_team"] = profile.get("role") in _TEAM_MANAGEMENT_ROLES


def _guard_entreprise(request):
    """Garde-fou des pages métier : exige une entreprise active en session.

    Non authentifié → login. Sans entreprise active : un admin plateforme est
    orienté vers la gestion des plans avec un message informatif (les pages
    métier ne le concernent pas), un utilisateur classique vers l'onboarding
    pour créer son espace de travail. Renvoie `None` si l'accès est autorisé.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")
    if not request.session.get("entreprise_id"):
        if request.session.get("is_platform_admin"):
            messages.info(request, _MSG_PAGE_ENTREPRISE)
            return redirect("plans_admin")
        return redirect("onboarding")
    return None


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
        #    que de bloquer (la session porte déjà le JWT nécessaire). Les flags
        #    admin sont posés sans contexte entreprise (`est_admin` restera à
        #    False, seul le statut plateforme est exploitable). Exception : un
        #    admin plateforme gère la plateforme, pas un espace client — il
        #    atterrit sur la gestion des plans, sans onboarding forcé.
        if not abonnements:
            _charger_flags_admin(request)
            if request.session.get("is_platform_admin"):
                return redirect("plans_admin")
            return redirect("onboarding")

        # 5. MVP : on sélectionne la première entreprise rattachée. Les flags
        #    admin sont posés APRÈS cette résolution : `est_admin` dépend de
        #    l'entreprise active, transmise via le header `x-entreprise-id`.
        request.session["entreprise_id"] = abonnements[0].get("id_entreprise")
        _charger_flags_admin(request)
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
    # Un admin plateforme sans entreprise n'a pas d'espace à créer : on
    # l'oriente vers ses pages d'administration (évite une création par
    # accident ; la double casquette volontaire n'est pas gérée à ce stade).
    if request.session.get("is_platform_admin"):
        messages.info(request, _MSG_ONBOARDING_ADMIN)
        return redirect("plans_admin")

    if request.method == "POST":
        form = EntrepriseForm(request.POST)
        if form.is_valid():
            try:
                entreprise = EntreprisesClient(request).create_entreprise(
                    form.to_api_payload()
                )
                request.session["entreprise_id"] = entreprise["id"]
                # Le créateur est propriétaire de l'entreprise : l'API le
                # rattache avec `est_admin=True` et le rôle PROPRIETAIRE, on
                # reflète ces statuts en session sans appel supplémentaire.
                request.session["is_entreprise_admin"] = True
                request.session["can_manage_team"] = True
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
