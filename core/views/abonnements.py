"""Vues du domaine abonnements (plans de la plateforme).

Trois volets :

- affichage (`/abonnements/`, utilisateur rattaché à une entreprise active) :
  liste des plans disponibles avec mise en évidence de l'abonnement actif de
  l'entreprise courante (croisement GET /abonnements/ et GET /abonnements/me) ;
- changement de plan (`/abonnements/<id>/choisir/`) et prolongation d'un mois
  (`/abonnements/prolonger/`), réservés aux admins de l'entreprise active :
  POST /abonnements/me/changer et /abonnements/me/prolonger, gardés par le
  flag de session `is_entreprise_admin` (posé au login) ;
- gestion (`/plans/...`, admin plateforme uniquement) : CRUD des plans via
  POST/PATCH/DELETE /abonnements/{id}. L'accès est gardé par le flag de session
  `is_platform_admin` (posé au login).

Dans les deux cas gardés, l'API reste juge de vérité (un 403 est traité comme
un accès refusé). Tout appel réseau passe par la couche `clients/`.
"""

from datetime import date
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
    _guard_entreprise,
)

# Rattachement des messages de conflit 409 aux champs du formulaire plan
# (traitement défensif : seul le DELETE documente un 409 au contrat, mais un
# conflit d'unicité sur le libellé resterait affiché proprement).
_CONFLICT_FIELD_KEYWORDS = {
    "libellé": "libelle",
    "libelle": "libelle",
}

# Message affiché quand un non-admin de l'entreprise tente une action sur
# l'abonnement — changement ou prolongation (garde-fou de session, ou 403
# renvoyé par l'API si le flag est obsolète).
_MSG_RESERVE_ADMIN_ENTREPRISE = (
    "La gestion de l'abonnement est réservée aux administrateurs de l'entreprise."
)

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


def _parse_date(value) -> date | None:
    """Convertit une date ISO de l'API (ex. "2026-08-03") en objet `date`.

    Best-effort : renvoie `None` si la valeur est absente ou inattendue, pour
    que l'affichage se dégrade proprement (champ simplement omis).
    """
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _with_display_dates(souscription: dict | None) -> dict | None:
    """Convertit les dates ISO d'une souscription en objets `date`.

    Permet au template d'utiliser le filtre `date` de Django pour un
    affichage au format français (l'API renvoie des chaînes ISO).
    """
    if souscription:
        souscription["date_debut"] = _parse_date(souscription.get("date_debut"))
        souscription["date_fin"] = _parse_date(souscription.get("date_fin"))
    return souscription


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
    refus = _guard_entreprise(request)
    if refus:
        return refus

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

    # Dates ISO -> objets `date`, pour un affichage français dans le template.
    souscription_active = _with_display_dates(souscription_active)
    souscription_inactive = _with_display_dates(souscription_inactive)

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
        "is_entreprise_admin": bool(request.session.get("is_entreprise_admin")),
        "current_plan_id": current_plan_id,
        "souscription_active": souscription_active,
        "souscription_inactive": souscription_inactive,
        "plan_inactif_libelle": plan_inactif_libelle,
        "statut_inactif_label": (
            _STATUT_LABELS.get(str(souscription_inactive.get("statut")), "inactif")
            if souscription_inactive
            else None
        ),
    }
    return render(request, "core/abonnements.html", context)


@require_POST
def abonnement_changer_view(request: HttpRequest, abonnement_id: int) -> HttpResponse:
    """Change le plan de l'entreprise active (POST /abonnements/me/changer).

    Action réservée aux administrateurs de l'entreprise : le flag de session
    `is_entreprise_admin` (posé au login) sert de garde-fou UI, l'API restant
    juge de vérité (un 403 est traité comme un accès refusé). L'entreprise
    ciblée est toujours celle du header `x-entreprise-id`, injecté par la
    couche clients. Le 409 porte un message métier actionnable (déjà sur ce
    plan, ou trop d'utilisateurs actifs pour le plan cible) : il est affiché
    tel quel plutôt que remplacé par un générique.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus
    if not request.session.get("is_entreprise_admin"):
        messages.error(request, _MSG_RESERVE_ADMIN_ENTREPRISE)
        return redirect("abonnements")

    try:
        AbonnementsClient(request).change_plan(abonnement_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceConflictError as e:
        messages.error(
            request,
            str(
                e.detail
                or "Changement d'abonnement impossible : conflit avec "
                "votre souscription actuelle."
            ),
        )
    except ResourceNotFoundError:
        messages.error(request, "Plan introuvable.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Changement d'abonnement refusé."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            messages.error(request, _MSG_RESERVE_ADMIN_ENTREPRISE)
        else:
            messages.error(request, "Erreur lors du changement d'abonnement.")
    else:
        messages.success(request, "Votre abonnement a été mis à jour avec succès.")

    return redirect("abonnements")


@require_POST
def abonnement_prolonger_view(request: HttpRequest) -> HttpResponse:
    """Prolonge d'un mois l'abonnement de l'entreprise active.

    Appelle POST /abonnements/me/prolonger (l'entreprise ciblée est celle du
    header `x-entreprise-id`, injecté par la couche clients). Action réservée
    aux administrateurs de l'entreprise : flag de session `is_entreprise_admin`
    en garde-fou UI, l'API restant juge de vérité. Le plan gratuit n'a pas
    d'échéance : l'API répond 409 et son message est affiché tel quel. En cas
    de succès, la nouvelle échéance renvoyée est reprise dans le message.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus
    if not request.session.get("is_entreprise_admin"):
        messages.error(request, _MSG_RESERVE_ADMIN_ENTREPRISE)
        return redirect("abonnements")

    try:
        souscription = AbonnementsClient(request).extend_plan()
    except TokenExpiredError:
        return redirect("login")
    except ResourceConflictError as e:
        messages.error(
            request,
            str(e.detail or "Cet abonnement ne peut pas être prolongé."),
        )
    except ResourceNotFoundError:
        messages.error(request, "Aucune souscription active à prolonger.")
    except APIValidationError as e:
        messages.error(request, str(e.detail or "Prolongation refusée."))
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            messages.error(request, _MSG_RESERVE_ADMIN_ENTREPRISE)
        else:
            messages.error(request, "Erreur lors de la prolongation de l'abonnement.")
    else:
        date_fin = (
            _parse_date(souscription.get("date_fin"))
            if isinstance(souscription, dict)
            else None
        )
        if date_fin:
            messages.success(
                request,
                "Votre abonnement a été prolongé jusqu'au "
                f"{date_fin.strftime('%d/%m/%Y')}.",
            )
        else:
            messages.success(request, "Votre abonnement a été prolongé d'un mois.")

    return redirect("abonnements")


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
