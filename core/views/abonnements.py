"""Vues du domaine abonnements (plans de la plateforme).

Deux volets :

- affichage (`/abonnements/`, tout utilisateur authentifié) : liste des plans
  disponibles avec mise en évidence de l'abonnement actif de l'entreprise
  courante (croisement GET /abonnements/ et GET /abonnements/me) ;
- gestion (`/plans/...`, admin plateforme uniquement) : CRUD des plans via
  POST/PATCH/DELETE /abonnements/{id}. L'accès est gardé par le flag de session
  `is_platform_admin` (posé au login), l'API restant juge de vérité (un 403 est
  traité comme un accès refusé). Tout appel réseau passe par la couche
  `clients/`.
"""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from clients.abonnements_client import AbonnementsClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from core.forms import AbonnementForm
from core.views.admins_plateforme import _MSG_ACCES_REFUSE
from core.views.auth import (
    _MSG_INDISPONIBLE,
    _appliquer_erreur_conflit,
    _appliquer_erreurs_api,
)

# Rattachement des messages de conflit 409 aux champs du formulaire plan
# (traitement défensif : seul le DELETE documente un 409 au contrat, mais un
# conflit d'unicité sur le libellé resterait affiché proprement).
_CONFLICT_FIELD_KEYWORDS = {
    "libellé": "libelle",
    "libelle": "libelle",
}

# Libellés affichés pour les statuts de souscription (enum StatutSouscription).
_STATUT_LABELS = {
    "actif": "actif",
    "expiré": "expiré",
    "suspendu": "suspendu",
    "annulé": "annulé",
}


def _format_tarif(value) -> str:
    """Formate un tarif en euros à la française (ex. « 29,90 »).

    La valeur arrive en chaîne décimale (ex. "29.90") : on retire les zéros non
    significatifs et on affiche la virgule décimale française.
    """
    try:
        formatted = format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, TypeError):
        return str(value)
    return formatted.replace(".", ",")


def _with_display_tarif(plans: list) -> list:
    """Enrichit chaque plan d'un champ d'affichage `tarif_affiche`."""
    for plan in plans:
        plan["tarif_affiche"] = _format_tarif(plan.get("tarif"))
    return plans


def _guard_platform_admin(request: HttpRequest) -> HttpResponse | None:
    """Garde-fou des pages de gestion : renvoie une redirection si accès refusé.

    Non authentifié → login ; authentifié mais non admin plateforme → home avec
    message d'erreur. Renvoie `None` si l'accès est autorisé.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")
    if not request.session.get("is_platform_admin"):
        messages.error(request, _MSG_ACCES_REFUSE)
        return redirect("home")
    return None


def _refus_api(request: HttpRequest) -> HttpResponse:
    """Traite un 403 renvoyé par l'API (flag de session obsolète, API juge)."""
    messages.error(request, _MSG_ACCES_REFUSE)
    return redirect("home")


def abonnements_view(request: HttpRequest) -> HttpResponse:
    """Affiche les plans disponibles et l'abonnement de l'entreprise active.

    La souscription courante provient de GET /abonnements/me : on retient celle
    de l'entreprise active (session) au statut `actif` pour mettre le plan en
    évidence. À défaut, la souscription la plus récente est signalée avec son
    statut réel (expiré, suspendu…), sans mise en évidence.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")

    client = AbonnementsClient(request)

    plans: list = []
    try:
        plans = _with_display_tarif(client.list_subscriptions())
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError:
        messages.error(request, "Erreur lors du chargement des abonnements.")

    # Résolution best-effort de la souscription courante : la page des plans
    # reste affichable même si /abonnements/me échoue (aucune mise en évidence).
    souscriptions: list = []
    try:
        souscriptions = client.get_my_subscription()
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        pass

    entreprise_id = request.session.get("entreprise_id")
    mes_souscriptions = [
        s for s in souscriptions if s.get("id_entreprise") == entreprise_id
    ]
    souscription_active = next(
        (s for s in mes_souscriptions if s.get("statut") == "actif"), None
    )

    # Sans souscription active, on signale la dernière souscription connue
    # (statut expiré/suspendu/annulé) via un bandeau informatif.
    souscription_inactive = None
    if souscription_active is None and mes_souscriptions:
        souscription_inactive = max(
            mes_souscriptions, key=lambda s: str(s.get("date_debut") or "")
        )

    current_plan_id = (
        souscription_active.get("id_abonnement") if souscription_active else None
    )
    plan_inactif_libelle = None
    if souscription_inactive:
        plan_inactif_libelle = next(
            (
                p.get("libelle")
                for p in plans
                if p.get("id") == souscription_inactive.get("id_abonnement")
            ),
            None,
        )

    context = {
        "plans": plans,
        "current_plan_id": current_plan_id,
        "souscription_active": souscription_active,
        "souscription_inactive": souscription_inactive,
        "plan_inactif_libelle": plan_inactif_libelle,
        "statut_inactif_label": (
            _STATUT_LABELS.get(souscription_inactive.get("statut"), "inactif")
            if souscription_inactive
            else None
        ),
    }
    return render(request, "core/abonnements.html", context)


def plans_admin_view(request: HttpRequest) -> HttpResponse:
    """Liste les plans avec les actions de gestion (admin plateforme)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    plans: list = []
    try:
        plans = _with_display_tarif(AbonnementsClient(request).list_subscriptions())
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Impossible de charger la liste des plans.")

    return render(request, "core/plans_admin.html", {"plans": plans})


def plan_create_view(request: HttpRequest) -> HttpResponse:
    """Crée un plan d'abonnement (admin plateforme)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    if request.method == "POST":
        form = AbonnementForm(request.POST)
        if form.is_valid():
            try:
                AbonnementsClient(request).create_subscription(form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError as e:
                if e.status_code == 403:
                    return _refus_api(request)
                messages.error(request, "Erreur lors de la création du plan.")
            else:
                messages.success(request, "Le plan a été créé avec succès.")
                return redirect("plans_admin")
    else:
        form = AbonnementForm()

    return render(request, "core/plan_form.html", {"form": form, "is_edit": False})


def plan_update_view(request: HttpRequest, abonnement_id: int) -> HttpResponse:
    """Édite un plan d'abonnement (formulaire pré-rempli, PATCH).

    Le contrat n'expose pas de route GET unitaire : le plan est retrouvé dans
    la liste GET /abonnements/.
    """
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    client = AbonnementsClient(request)

    try:
        plans = client.list_subscriptions()
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("plans_admin")
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Erreur lors du chargement du plan.")
        return redirect("plans_admin")

    plan = next((p for p in plans if p.get("id") == abonnement_id), None)
    if plan is None:
        messages.error(request, "Plan introuvable.")
        return redirect("plans_admin")

    if request.method == "POST":
        form = AbonnementForm(request.POST, is_edit=True)
        if form.is_valid():
            try:
                client.update_subscription(abonnement_id, form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except ResourceNotFoundError:
                messages.error(request, "Plan introuvable.")
                return redirect("plans_admin")
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError as e:
                if e.status_code == 403:
                    return _refus_api(request)
                messages.error(request, "Erreur lors de la modification du plan.")
            else:
                messages.success(request, "Le plan a été modifié avec succès.")
                return redirect("plans_admin")
    else:
        form = AbonnementForm(initial=plan, is_edit=True)

    return render(
        request,
        "core/plan_form.html",
        {"form": form, "is_edit": True, "plan": plan},
    )


@require_POST
def plan_delete_view(request: HttpRequest, abonnement_id: int) -> HttpResponse:
    """Supprime un plan d'abonnement (admin plateforme).

    L'API renvoie un 409 si le plan est encore souscrit par au moins une
    entreprise : le message du corps d'erreur est affiché tel quel.
    """
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        AbonnementsClient(request).delete_subscription(abonnement_id)
        messages.success(request, "Le plan a été supprimé.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceConflictError as e:
        messages.error(
            request,
            str(
                e.detail
                or "Impossible de supprimer ce plan : il est encore souscrit "
                "par une ou plusieurs entreprises."
            ),
        )
    except ResourceNotFoundError:
        messages.error(request, "Plan introuvable.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Suppression refusée."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Erreur lors de la suppression du plan.")

    return redirect("plans_admin")
