"""Vues d'administration des entreprises abonnées (backoffice plateforme).

Réservées aux administrateurs de plateforme (garde-fou de session
`is_platform_admin`, l'API restant juge de vérité). Ces écrans agissent sur
n'importe quelle entreprise : les appels passent par `AdministrationClient`,
qui ne transmet pas le header de tenant.

Ce module couvre la liste (recherche, filtres statut d'abonnement et
actif/suspendu, pagination — état porté par les query params), le détail d'une
entreprise, la correction de son identité légale, et les actions de gestion :
changement de plan, prolongation, résiliation, suspension, réactivation et
suppression.

La suspension est réversible et sans perte : c'est la réponse recommandée face
à une entreprise dont les données interdisent la suppression.

Tout appel réseau passe par la couche `clients/`.
"""

from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from clients.abonnements_client import AbonnementsClient
from clients.administration_client import AdministrationClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from core.formatting import format_iso_date_fr
from core.forms import EntrepriseAdminForm
from core.pagination import (
    PAGE_SIZE,
    base_querystring,
    build_pagination,
    parse_bool_filter,
    parse_page,
)
from core.views.abonnements import _guard_platform_admin, _refus_api
from core.views.administration import (
    STATUTS_SOUSCRIPTION,
    STATUTS_SOUSCRIPTION_VALUES,
    relay_guard_refusal,
    with_display_souscription,
    with_display_souscriptions,
)
from core.views.auth import (
    _MSG_INDISPONIBLE,
    _appliquer_erreur_conflit,
    _appliquer_erreurs_api,
)

# Longueur maximale du motif de suspension acceptée par l'API
# (schémas SuspensionRequest, partagé par la suspension et la résiliation).
_MOTIF_MAX_LENGTH = 255

# Rattachement du message de conflit 409 (SIRET déjà rattaché à une autre
# entreprise) au champ concerné du formulaire.
_CONFLICT_FIELD_KEYWORDS = {"siret": "siret"}

# Compteurs dont une valeur non nulle empêche la suppression d'une entreprise,
# avec leur libellé au singulier et au pluriel.
_COMPTEURS_BLOQUANTS = (
    ("factures_total", "facture", "factures"),
    ("clients", "client", "clients"),
    ("produits", "produit", "produits"),
    ("documents", "document", "documents"),
)


def administration_entreprises_view(request: HttpRequest) -> HttpResponse:
    """Liste les entreprises abonnées avec leurs actions de gestion."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    # Lecture défensive des query params.
    search = request.GET.get("q", "").strip()
    est_actif_raw = request.GET.get("est_actif", "")
    est_actif = parse_bool_filter(est_actif_raw)
    statut_raw = request.GET.get("statut", "")
    statut = statut_raw if statut_raw in STATUTS_SOUSCRIPTION_VALUES else ""
    page = parse_page(request.GET.get("page"))
    skip = (page - 1) * PAGE_SIZE

    items: list = []
    total = 0
    try:
        result = AdministrationClient(request).list_entreprises(
            recherche=search or None,
            est_actif=est_actif,
            statut_abonnement=statut or None,
            skip=skip,
            limit=PAGE_SIZE,
        )
        items = with_display_souscription(result.get("items", []))
        total = result.get("total", 0)
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        # En lecture, un 403 ne peut signifier qu'un accès refusé.
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Impossible de charger la liste des entreprises.")

    pagination = build_pagination(page, total)

    context = {
        "items": items,
        "total": total,
        "base_query": base_querystring(request),
        # Valeurs courantes des filtres, pour ré-afficher l'état du formulaire.
        "search": search,
        "est_actif": est_actif_raw,
        "statut": statut,
        "statuts": STATUTS_SOUSCRIPTION,
        "motif_max_length": _MOTIF_MAX_LENGTH,
        **pagination,
    }
    return render(request, "core/administration_entreprises.html", context)


def administration_entreprise_detail_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Affiche la fiche complète d'une entreprise et ses actions de gestion.

    Un seul appel (GET /administration/entreprises/{id}) rapporte l'identité,
    les membres, l'historique des souscriptions et les compteurs de données.
    Les plans disponibles sont chargés en complément pour alimenter le
    changement de plan ; leur absence n'empêche pas de consulter la fiche.
    """
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        entreprise = AdministrationClient(request).get_entreprise(entreprise_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise introuvable.")
        return redirect("admin_entreprises")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("admin_entreprises")
    except APIClientError as e:
        # En lecture, un 403 ne peut signifier qu'un accès refusé.
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Impossible de charger le détail de l'entreprise.")
        return redirect("admin_entreprises")

    # Champs d'affichage : statut de la souscription courante, dates FR.
    with_display_souscription([entreprise])
    entreprise["date_creation_fr"] = format_iso_date_fr(entreprise.get("date_creation"))
    entreprise["date_suspension_fr"] = format_iso_date_fr(
        entreprise.get("date_suspension")
    )
    membres = entreprise.get("membres") or []
    for membre in membres:
        membre["derniere_connexion_fr"] = format_iso_date_fr(
            membre.get("date_derniere_connexion")
        )
    souscriptions = with_display_souscriptions(entreprise.get("souscriptions") or [])
    compteurs = entreprise.get("compteurs") or {}

    souscription = entreprise.get("souscription") or {}

    plans: list = []
    try:
        plans = AbonnementsClient(request).list_subscriptions()
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        # Sans la liste des plans, la fiche reste consultable : seul le
        # changement de plan disparaît de l'écran.
        messages.error(request, "Impossible de charger la liste des plans.")

    # Le plan courant est retiré des choix : le proposer ne mènerait qu'à un
    # 409 « déjà sur ce plan ».
    plans_disponibles = [
        plan for plan in plans if plan.get("id") != souscription.get("id_abonnement")
    ]

    context = {
        "entreprise": entreprise,
        "membres": membres,
        "souscriptions": souscriptions,
        "compteurs": compteurs,
        "souscription": souscription,
        "plans": plans_disponibles,
        "blocage_suppression": _blocage_suppression(compteurs),
        "motif_max_length": _MOTIF_MAX_LENGTH,
    }
    return render(request, "core/administration_entreprise_detail.html", context)


def _blocage_suppression(compteurs: dict[str, Any]) -> str:
    """Décrit ce qui empêche la suppression de l'entreprise, sinon chaîne vide.

    Préaffichage seulement, destiné à ne pas proposer un bouton qui ne peut
    qu'échouer : l'API reste juge et refuse en 403 (facture émise, conservation
    obligatoire) ou en 409 (toute autre donnée restante).

    Args:
        compteurs (dict[str, Any]): Volumétrie de l'entreprise (schéma
            CompteursEntreprise). Obligatoire.

    Returns:
        str: Message d'obstacle à afficher, ou chaîne vide si l'entreprise est
        vierge de toute donnée.
    """
    donnees = [
        f"{compteurs.get(cle) or 0} {singulier if compteurs.get(cle) == 1 else pluriel}"
        for cle, singulier, pluriel in _COMPTEURS_BLOQUANTS
        if compteurs.get(cle)
    ]
    if not donnees:
        return ""
    detail = ", ".join(donnees)
    if compteurs.get("factures_scellees"):
        return (
            f"Suppression impossible : cette entreprise porte {detail}. Une facture "
            "émise ne peut jamais être supprimée (obligation de conservation) — la "
            "suspension est la seule mesure possible."
        )
    return (
        f"Suppression impossible : cette entreprise contient encore des données "
        f"({detail}). Supprimez-les au préalable, ou suspendez l'entreprise."
    )


def administration_entreprise_update_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Corrige l'identité légale d'une entreprise (PATCH partiel).

    Se limite à la raison sociale, au SIRET et à la forme juridique — l'état de
    suspension et l'abonnement relèvent des actions dédiées. La réponse du PATCH
    est un `EntrepriseAdminRead` allégé (sans membres ni souscription) : on ne la
    rend jamais, on redirige vers le détail qui recharge la fiche complète.
    """
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    client = AdministrationClient(request)

    try:
        entreprise = client.get_entreprise(entreprise_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise introuvable.")
        return redirect("admin_entreprises")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("admin_entreprises")
    except APIClientError as e:
        if e.status_code == 403:
            return _refus_api(request)
        messages.error(request, "Impossible de charger le détail de l'entreprise.")
        return redirect("admin_entreprises")

    if request.method == "POST":
        form = EntrepriseAdminForm(request.POST)
        if form.is_valid():
            try:
                client.update_entreprise(entreprise_id, form.to_api_payload())
            except TokenExpiredError:
                return redirect("login")
            except ResourceConflictError as e:
                _appliquer_erreur_conflit(form, e.detail, _CONFLICT_FIELD_KEYWORDS)
            except APIValidationError as e:
                _appliquer_erreurs_api(form, e.detail)
            except ResourceNotFoundError:
                messages.error(request, "Entreprise introuvable.")
                return redirect("admin_entreprises")
            except APIUnavailableError:
                messages.error(request, _MSG_INDISPONIBLE)
            except APIClientError as e:
                if e.status_code == 403:
                    return _refus_api(request)
                messages.error(
                    request, "Erreur lors de la modification de l'entreprise."
                )
            else:
                messages.success(request, "L'entreprise a été modifiée avec succès.")
                return _redirect_detail(entreprise_id)
    else:
        form = EntrepriseAdminForm(initial=entreprise)

    return render(
        request,
        "core/administration_entreprise_form.html",
        {"form": form, "entreprise": entreprise},
    )


@require_POST
def administration_entreprise_change_plan_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Bascule l'entreprise sur un autre plan d'abonnement."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        id_abonnement = int(request.POST.get("id_abonnement", ""))
    except ValueError:
        messages.error(request, "Veuillez sélectionner un plan d'abonnement.")
        return _redirect_detail(entreprise_id)

    try:
        AdministrationClient(request).change_plan(entreprise_id, id_abonnement)
        messages.success(request, "Le plan d'abonnement a été changé.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise ou plan introuvable.")
    except ResourceConflictError as e:
        # Déjà sur ce plan, ou trop d'utilisateurs actifs pour le plan visé.
        relay_guard_refusal(request, e.detail, "Changement de plan refusé.")
    except APIValidationError as e:
        relay_guard_refusal(request, e.detail, "Changement de plan refusé.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        # En action, un 403 porte un garde-fou métier : on relaie son message.
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Changement de plan refusé.")
        else:
            messages.error(request, "Erreur lors du changement de plan.")

    return _redirect_detail(entreprise_id)


@require_POST
def administration_entreprise_extend_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Prolonge d'un mois l'abonnement payant de l'entreprise."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        AdministrationClient(request).extend_subscription(entreprise_id)
        messages.success(request, "L'abonnement a été prolongé d'un mois.")
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError as e:
        # Couvre aussi l'absence de souscription active à prolonger.
        relay_guard_refusal(request, e.detail, "Aucun abonnement à prolonger.")
    except ResourceConflictError as e:
        # Le plan gratuit n'expire pas : rien à prolonger.
        relay_guard_refusal(request, e.detail, "Prolongation refusée.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Prolongation refusée.")
        else:
            messages.error(request, "Erreur lors de la prolongation de l'abonnement.")

    return _redirect_detail(entreprise_id)


@require_POST
def administration_entreprise_cancel_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Résilie l'abonnement de l'entreprise (motif optionnel)."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    motif = request.POST.get("motif", "").strip()[:_MOTIF_MAX_LENGTH]

    try:
        AdministrationClient(request).cancel_subscription(entreprise_id, motif or None)
        messages.success(
            request,
            "L'abonnement a été résilié : l'entreprise perd l'accès à son espace "
            "de travail, sans perte de données.",
        )
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError as e:
        relay_guard_refusal(request, e.detail, "Aucun abonnement à résilier.")
    except ResourceConflictError as e:
        # Souscription déjà résiliée.
        relay_guard_refusal(request, e.detail, "Résiliation refusée.")
    except APIValidationError as e:
        relay_guard_refusal(request, e.detail, "Résiliation refusée.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Résiliation refusée.")
        else:
            messages.error(request, "Erreur lors de la résiliation de l'abonnement.")

    return _redirect_detail(entreprise_id)


@require_POST
def administration_entreprise_delete_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Supprime définitivement une entreprise vierge de toute donnée.

    Les compteurs affichés sur la fiche préviennent l'échec, mais l'API reste
    juge : un refus (403 facture émise, 409 données restantes) est relayé tel
    quel et l'administrateur reste sur le détail.
    """
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        AdministrationClient(request).delete_entreprise(entreprise_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise introuvable.")
        return redirect("admin_entreprises")
    except ResourceConflictError as e:
        relay_guard_refusal(request, e.detail, "Suppression refusée.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Suppression refusée.")
        else:
            messages.error(request, "Erreur lors de la suppression de l'entreprise.")
    else:
        messages.success(request, "L'entreprise a été supprimée.")
        # La fiche n'existe plus : retour à la liste.
        return redirect("admin_entreprises")

    return _redirect_detail(entreprise_id)


@require_POST
def administration_entreprise_suspend_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Suspend une entreprise (motif optionnel), puis revient à la liste."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    motif = request.POST.get("motif", "").strip()[:_MOTIF_MAX_LENGTH]

    try:
        AdministrationClient(request).suspend_entreprise(entreprise_id, motif or None)
        messages.success(
            request,
            "L'entreprise a été suspendue : ses membres n'ont plus accès à leur "
            "espace de travail.",
        )
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise introuvable.")
    except APIValidationError as e:
        relay_guard_refusal(request, e.detail, "Suspension refusée.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        # En action, un 403 porte un garde-fou métier : on relaie son message.
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Suspension refusée.")
        else:
            messages.error(request, "Erreur lors de la suspension de l'entreprise.")

    return _redirect_apres_action(request, entreprise_id)


@require_POST
def administration_entreprise_reactivate_view(
    request: HttpRequest, entreprise_id: int
) -> HttpResponse:
    """Réactive une entreprise suspendue, puis revient à la liste."""
    refus = _guard_platform_admin(request)
    if refus:
        return refus

    try:
        AdministrationClient(request).reactivate_entreprise(entreprise_id)
        messages.success(
            request,
            "L'entreprise a été réactivée : ses membres retrouvent l'accès à "
            "leur espace de travail.",
        )
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Entreprise introuvable.")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        if e.status_code == 403:
            relay_guard_refusal(request, e.detail, "Réactivation refusée.")
        else:
            messages.error(request, "Erreur lors de la réactivation de l'entreprise.")

    return _redirect_apres_action(request, entreprise_id)


def _redirect_detail(entreprise_id: int) -> HttpResponse:
    """Redirige vers la fiche de l'entreprise (PRG après une action).

    Les actions renvoient un schéma allégé (`EntrepriseAdminRead` ou
    `EntrepriseAbonnementRead`) : le rendre laisserait un écran amputé de ses
    membres et de son historique. On recharge donc la fiche complète.
    """
    return redirect("admin_entreprise_detail", entreprise_id=entreprise_id)


def _redirect_apres_action(request: HttpRequest, entreprise_id: int) -> HttpResponse:
    """Revient à l'écran d'où l'action a été déclenchée (fiche ou liste).

    Suspension et réactivation sont proposées des deux côtés : le champ caché
    `origine` posé par le formulaire appelant indique lequel des deux écrans
    reprendre. Sa valeur ne sert qu'à choisir entre deux URL internes.
    """
    if request.POST.get("origine") == "detail":
        return _redirect_detail(entreprise_id)
    return _redirect_apres_action(request, entreprise_id)


def _redirect_liste(request: HttpRequest) -> HttpResponse:
    """Redirige vers la liste en préservant recherche, filtres et page.

    L'état de la liste vit dans les query params : après une action, on y
    revient tel quel plutôt que sur une liste remise à zéro. Le champ `retour`
    est posé par le formulaire appelant ; il est ré-encodé avant usage (sa
    valeur vient du client et ne doit pas partir telle quelle dans l'en-tête
    `Location`).
    """
    query = QueryDict(request.POST.get("retour", "")).urlencode()
    url = reverse("admin_entreprises")
    return redirect(f"{url}?{query}" if query else url)
