import re

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render

from clients.abonnements_client import AbonnementsClient
from clients.api_client import APIAuthClient
from clients.clients_client import ClientsClient
from clients.comptes_client import ComptesClient
from clients.entreprises_client import EntreprisesClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceNotFoundError,
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

# Clé de session du résultat SIRENE en attente à l'onboarding. Un utilisateur
# ne crée qu'un premier espace de travail à la fois : pas de portée
# supplémentaire (contrairement au récap, scopé par facture).
_SIRENE_SESSION_KEY = "onboarding_sirene"

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


def _load_entreprise_profile(request):
    """Renseigne en session le SIRET et la raison sociale de l'entreprise active.

    Appelle GET /entreprises/me (le header `x-entreprise-id` est injecté par
    la couche clients depuis `entreprise_id`, déjà résolu en session). Le SIRET
    sert au récap de facture pour signaler une divergence avec le SIRET
    émetteur extrait par l'OCR, la raison sociale au bandeau du tableau de
    bord : les deux sont posés ici pour éviter un appel API à chaque
    affichage. Cet enrichissement ne doit JAMAIS bloquer la connexion : en cas
    d'échec ou de champ absent, la clé correspondante reste absente (l'alerte
    de divergence est désactivée, le bandeau s'affiche sans nom).
    """
    try:
        entreprise = EntreprisesClient(request).get_my_entreprise()
    except APIClientError:
        return
    if not isinstance(entreprise, dict):
        return
    if entreprise.get("siret"):
        request.session["entreprise_siret"] = entreprise["siret"]
    if entreprise.get("raison_sociale"):
        request.session["entreprise_nom"] = entreprise["raison_sociale"]


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


def _redirect_to_user_space(request):
    """Redirige un utilisateur authentifié vers son espace approprié.

    Destination post-login factorisée, partagée par `login_view` et le garde
    des pages publiques : un admin plateforme sans entreprise gère les plans,
    un utilisateur sans entreprise passe par l'onboarding, sinon (entreprise
    active) il atterrit sur son tableau de bord — pas sur la vitrine publique,
    qui reste accessible via la marque du header. Suppose les flags de session
    déjà posés (voir `_charger_flags_admin`).
    """
    if not request.session.get("entreprise_id"):
        if request.session.get("is_platform_admin"):
            return redirect("plans_admin")
        return redirect("onboarding")
    return redirect("dashboard")


def _redirect_if_authenticated(request):
    """Garde des pages publiques (connexion, inscription, mots de passe).

    Empêche un utilisateur déjà connecté de « se reconnecter » par-dessus sa
    session (comportement incohérent) : renvoie une redirection vers son espace
    le cas échéant, sinon `None` (la page publique s'affiche normalement).
    """
    if request.session.get("is_authenticated"):
        return _redirect_to_user_space(request)
    return None


def login_view(request):
    deja_connecte = _redirect_if_authenticated(request)
    if deja_connecte:
        return deja_connecte

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
            return _redirect_to_user_space(request)

        # 5. MVP : on sélectionne la première entreprise rattachée. Les flags
        #    admin sont posés APRÈS cette résolution : `est_admin` dépend de
        #    l'entreprise active, transmise via le header `x-entreprise-id`.
        request.session["entreprise_id"] = abonnements[0].get("id_entreprise")
        _charger_flags_admin(request)
        _load_entreprise_profile(request)
        return _redirect_to_user_space(request)

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
    deja_connecte = _redirect_if_authenticated(request)
    if deja_connecte:
        return deja_connecte

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
    deja_connecte = _redirect_if_authenticated(request)
    if deja_connecte:
        return deja_connecte

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
    deja_connecte = _redirect_if_authenticated(request)
    if deja_connecte:
        return deja_connecte

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


def _normalize_identifiant(value):
    """Normalise un SIREN/SIRET saisi : espaces et points retirés.

    Les numéros sont couramment recopiés avec des séparateurs (« 123 456 789
    00012 ») : on les retire avant de contrôler le format et d'appeler l'API.
    """
    text = str(value or "").strip()
    # Espace simple, insécable (U+00A0), fine insécable (U+202F), point et
    # tiret : les séparateurs courants d'un numéro copié-collé.
    for separateur in (" ", " ", " ", ".", "-"):
        text = text.replace(separateur, "")
    return text


def _sirene_initial(company, submitted):
    """Fusionne le résultat SIRENE avec la saisie en cours de l'onboarding.

    La donnée officielle prime (l'utilisateur a demandé la recherche), mais un
    champ absent de SIRENE — tous les champs du schéma sont nullable — ne doit
    jamais effacer ce qui était déjà saisi.

    Args:
        company (dict): Réponse de GET /clients/recherche-sirene/{identifiant}.
            Obligatoire.
        submitted (dict): Valeurs présentes dans le formulaire au moment de la
            recherche. Obligatoire.

    Returns:
        dict: Valeurs `initial` du formulaire entreprise.
    """
    raison_sociale = str(company.get("raison_sociale") or "").strip()
    siret = _normalize_identifiant(company.get("siret"))
    return {
        "nom_entreprise": raison_sociale or submitted["nom_entreprise"],
        # Une recherche par SIREN (9 chiffres) renvoie le SIRET du siège :
        # on récupère ainsi les 14 chiffres attendus par l'API entreprises.
        "siret": siret or submitted["siret"],
    }


def _handle_onboarding_sirene_lookup(request):
    """Recherche SIRENE du SIRET/SIREN saisi à l'onboarding (aide non bloquante).

    Même mécanisme que la fenêtre SIRENE du récap de facture : la vue relaie
    l'appel (le navigateur ne touche jamais l'API SIRENE), dépose le résultat
    en session puis redirige (PRG). Le rendu suivant consomme la clé pour
    pré-remplir le formulaire et afficher l'encart de vérification. Tous les
    échecs sont non bloquants : avertissement, saisie conservée, création
    manuelle toujours possible.

    Args:
        request (HttpRequest): Requête Django courante (POST). Obligatoire.

    Returns:
        HttpResponse: Redirection vers l'onboarding (ou le login si la session
        a expiré).
    """
    submitted = {
        "nom_entreprise": (request.POST.get("nom_entreprise") or "").strip(),
        "siret": _normalize_identifiant(request.POST.get("siret")),
    }
    identifiant = submitted["siret"]
    pending = {"initial": submitted}

    if not re.fullmatch(r"\d{9}|\d{14}", identifiant):
        messages.warning(
            request,
            "Renseignez un SIRET (14 chiffres) ou un SIREN (9 chiffres) pour "
            "lancer la recherche, ou saisissez les informations manuellement.",
        )
    else:
        try:
            company = ClientsClient(request).search_sirene(identifiant)
        except TokenExpiredError:
            return redirect("login")
        except (ResourceNotFoundError, APIValidationError):
            messages.warning(
                request,
                f"Le numéro {identifiant} est introuvable dans la base SIRENE : "
                "vérifiez-le, ou saisissez les informations manuellement.",
            )
        except APIClientError:
            messages.warning(
                request,
                "La recherche SIRENE est indisponible pour le moment : réessayez "
                "plus tard, ou saisissez les informations manuellement.",
            )
        else:
            if isinstance(company, dict):
                pending = {
                    "result": company,
                    "initial": _sirene_initial(company, submitted),
                }
            else:
                messages.warning(
                    request,
                    "La recherche SIRENE n'a renvoyé aucune donnée exploitable : "
                    "saisissez les informations manuellement.",
                )

    request.session[_SIRENE_SESSION_KEY] = pending
    return redirect("onboarding")


def onboarding_view(request):
    """Création du premier espace de travail (POST /entreprises/).

    Écran présenté après login quand l'utilisateur n'a aucune entreprise
    rattachée. Le JWT est déjà en session (posé par `login_view`) : le client
    entreprises le réutilise, sans `x-entreprise-id` (pas encore d'entreprise).
    Après création, on initialise `entreprise_id` en session et on donne accès
    à l'application.

    Le bouton « Rechercher » du champ SIRET (action `sirene_lookup`) est une
    aide facultative : il pré-remplit le nom et le SIRET depuis la base SIRENE
    et affiche les autres informations officielles (adresse, activité) pour
    vérification — les champs restent éditables et la saisie manuelle reste
    possible de bout en bout.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")
    # Déjà un espace de travail : rien à créer, on renvoie vers l'app.
    if request.session.get("entreprise_id"):
        return redirect("dashboard")
    # Un admin plateforme sans entreprise n'a pas d'espace à créer : on
    # l'oriente vers ses pages d'administration (évite une création par
    # accident ; la double casquette volontaire n'est pas gérée à ce stade).
    if request.session.get("is_platform_admin"):
        messages.info(request, _MSG_ONBOARDING_ADMIN)
        return redirect("plans_admin")

    if request.method == "POST":
        # Recherche SIRENE : traitée avant toute validation (le formulaire peut
        # être incomplet à ce stade) et sortie par redirection, la création
        # d'entreprise n'est pas concernée.
        if request.POST.get("action") == "sirene_lookup":
            return _handle_onboarding_sirene_lookup(request)

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
                # Le SIRET (optionnel) et la raison sociale sont déjà dans la
                # réponse de création : on les pose en session sans appel
                # supplémentaire (alerte de divergence du récap de facture,
                # bandeau du tableau de bord).
                if entreprise.get("siret"):
                    request.session["entreprise_siret"] = entreprise["siret"]
                if entreprise.get("raison_sociale"):
                    request.session["entreprise_nom"] = entreprise["raison_sociale"]
                messages.success(
                    request, "Votre espace de travail a été créé avec succès."
                )
                return redirect("dashboard")
            except TokenExpiredError:
                return redirect("login")
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError:
                messages.error(request, "Impossible de créer l'espace de travail.")
        return render(request, "core/onboarding.html", {"form": form})

    # Résultat d'une recherche SIRENE en attente : consommé une seule fois
    # (pop) pour pré-remplir le formulaire et afficher l'encart de vérification.
    pending = request.session.pop(_SIRENE_SESSION_KEY, None) or {}
    return render(
        request,
        "core/onboarding.html",
        {
            "form": EntrepriseForm(initial=pending.get("initial") or {}),
            "sirene_result": pending.get("result"),
        },
    )
