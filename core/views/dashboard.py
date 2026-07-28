"""Vue du tableau de bord (accueil connecté).

Page d'atterrissage après connexion pour un utilisateur avec une entreprise
active : bandeau d'accueil, quatre indicateurs du moment, actions rapides et
les cinq dernières factures.

Deux appels réseau seulement, indépendants l'un de l'autre :

1. GET /factures/statistiques **sans dates** (12 mois glissants côté API). La
   fenêtre large est volontaire : `paiement` et `brouillons` sont bornés par
   la période, un appel sur le seul mois en cours masquerait les impayés et
   les brouillons plus anciens — précisément ceux qui traînent. Le CA du mois
   et sa variation sont dérivés de `par_mois` (série mensuelle continue), donc
   sans second appel.
2. GET /factures/ (limite 5, sans filtre de statut) pour l'activité récente.

Chaque appel dégrade indépendamment : si les statistiques sont indisponibles,
les cartes affichent un état local et le reste de la page reste utilisable, et
inversement. Aucune donnée (entreprise neuve) affiche des zéros propres, pas
une erreur.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.entreprises_client import EntreprisesClient
from clients.exceptions import APIClientError, TokenExpiredError
from clients.factures_client import FacturesClient
from core.formatting import format_amount, format_date_fr, parse_iso_date, to_decimal
from core.views.auth import _guard_entreprise
from core.views.factures import _with_status_badge

# Nombre de factures affichées dans le tableau « activité récente ».
_RECENT_INVOICES_LIMIT = 5


def _previous_month_key(today: date) -> str:
    """Clé `AAAA-MM` du mois précédant `today` (bascule d'année gérée)."""
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def _month_revenue(par_mois: Any, key: str) -> Decimal:
    """CA TTC du mois `key` dans la série `par_mois` (0 si le mois est absent).

    Le contrat garantit une série continue couvrant toute la période (mois
    vides renvoyés à zéro) : un mois manquant ne peut venir que d'une réponse
    inattendue, auquel cas zéro est la bonne valeur d'affichage.

    Args:
        par_mois (Any): Liste `par_mois` de la réponse, possiblement absente
            ou d'une autre forme. Obligatoire.
        key (str): Mois recherché, au format `AAAA-MM`. Obligatoire.

    Returns:
        Decimal: Le CA TTC du mois, ou zéro.
    """
    if not isinstance(par_mois, list):
        return Decimal(0)
    for point in par_mois:
        if isinstance(point, dict) and str(point.get("mois") or "") == key:
            return to_decimal(point.get("ca_ttc")) or Decimal(0)
    return Decimal(0)


def _month_variation(current: Decimal, previous: Decimal) -> dict[str, str] | None:
    """Calcule la variation du CA d'un mois sur l'autre, en pourcentage.

    Renvoie `None` quand la comparaison n'a pas de sens : mois précédent nul
    (démarrage d'activité — jamais de division par zéro) ou négatif (avoirs
    supérieurs au CA, un pourcentage y serait trompeur).

    Args:
        current (Decimal): CA TTC du mois en cours. Obligatoire.
        previous (Decimal): CA TTC du mois précédent. Obligatoire.

    Returns:
        dict[str, str] | None: `valeur` (pourcentage absolu formaté, ex.
        « 12,4 ») et `sens` (« hausse », « baisse » ou « stable »), ou `None`.
    """
    if previous <= 0:
        return None
    ecart = (current - previous) / previous * 100
    arrondi = ecart.quantize(Decimal("0.1"))
    if arrondi == 0:
        sens = "stable"
    else:
        sens = "hausse" if arrondi > 0 else "baisse"
    return {"valeur": f"{abs(arrondi)}".replace(".", ","), "sens": sens}


def _company_name(request: HttpRequest) -> str | None:
    """Raison sociale de l'entreprise active, mémorisée en session.

    Posée au login et à l'onboarding : en régime normal, aucun appel réseau
    ici. Le repli (session ouverte avant l'ajout de la clé) fait un unique
    GET /entreprises/me best-effort dont le résultat est mémorisé à son tour.
    Un échec n'est jamais bloquant : le bandeau affiche alors « Bonjour » et la
    date, sans nom.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.

    Returns:
        str | None: La raison sociale, ou `None` si elle reste indisponible.

    Raises:
        TokenExpiredError: Session expirée (seule exception propagée).
    """
    nom = request.session.get("entreprise_nom")
    if nom:
        return str(nom)
    try:
        entreprise = EntreprisesClient(request).get_my_entreprise()
    except TokenExpiredError:
        raise
    except APIClientError:
        return None
    if not isinstance(entreprise, dict):
        return None
    raison_sociale = entreprise.get("raison_sociale")
    if raison_sociale:
        request.session["entreprise_nom"] = raison_sociale
        return str(raison_sociale)
    return None


def _build_indicators(stats: Any, today: date) -> dict[str, Any]:
    """Prépare les quatre indicateurs du tableau de bord depuis les statistiques.

    Le CA du mois et sa variation sont lus dans `par_mois` (et non dans
    `totaux`, qui couvre toute la fenêtre de 12 mois) ; l'encours et les
    brouillons sont pris tels quels sur toute la période, pour ne pas ignorer
    une facture impayée ou un brouillon plus ancien. Lecture défensive : toute
    partie absente ou malformée retombe sur une valeur neutre plutôt que de
    faire échouer le rendu.

    Args:
        stats (Any): Réponse de GET /factures/statistiques (schéma
            StatistiquesFactures). Obligatoire.
        today (date): Date du jour, qui désigne le mois en cours. Obligatoire.

    Returns:
        dict[str, Any]: Entrées de contexte des cartes KPI et de l'encart des
        devises exclues.
    """
    if not isinstance(stats, dict):
        stats = {}
    devise = str(stats.get("devise") or "EUR")

    par_mois = stats.get("par_mois")
    ca_mois = _month_revenue(par_mois, f"{today.year}-{today.month:02d}")
    ca_mois_precedent = _month_revenue(par_mois, _previous_month_key(today))

    paiement = stats.get("paiement") if isinstance(stats.get("paiement"), dict) else {}
    en_retard = to_decimal(paiement.get("montant_en_retard")) or Decimal(0)

    brouillons = (
        stats.get("brouillons") if isinstance(stats.get("brouillons"), dict) else {}
    )
    brouillons_nombre = brouillons.get("nombre")

    exclues = stats.get("devises_exclues")
    devises_exclues = [
        item
        for item in (exclues if isinstance(exclues, list) else [])
        if isinstance(item, dict) and item.get("devise")
    ]

    # Début de la fenêtre réellement agrégée par l'API : sert à préciser sur
    # quelle profondeur portent l'encours et les brouillons.
    periode = stats.get("periode")
    periode_debut = parse_iso_date(
        periode.get("date_min") if isinstance(periode, dict) else None
    )

    return {
        "devise_code": devise,
        "ca_mois": format_amount(ca_mois, devise),
        "ca_variation": _month_variation(ca_mois, ca_mois_precedent),
        "restant_a_encaisser": format_amount(
            paiement.get("restant_a_encaisser") or 0, devise
        ),
        "montant_en_retard": format_amount(en_retard, devise),
        "en_retard_actif": en_retard > 0,
        "brouillons_nombre": (
            brouillons_nombre if isinstance(brouillons_nombre, int) else 0
        ),
        "brouillons_montant": format_amount(brouillons.get("montant_ttc") or 0, devise),
        "devises_exclues": devises_exclues,
        "periode_debut": format_date_fr(periode_debut) if periode_debut else None,
    }


def _prepare_recent_invoices(items: Any) -> list[dict[str, Any]]:
    """Prépare les dernières factures pour l'affichage du tableau court.

    Reprend le badge de statut de la liste des factures (`_with_status_badge`,
    source unique du mapping) et ajoute ce que le template ne peut pas
    calculer : date au format français, montant formaté et destination du lien
    — un brouillon ouvre son récap éditable, une facture émise son aperçu.

    Args:
        items (Any): Items de GET /factures/ (schéma FactureListItem),
            possiblement absents ou d'une autre forme. Obligatoire.

    Returns:
        list[dict[str, Any]]: Factures enrichies, les éléments inexploitables
        étant écartés.
    """
    prepared = []
    for item in _with_status_badge(items if isinstance(items, list) else []):
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        item = dict(item)
        emission = parse_iso_date(item.get("date_emission"))
        item["date_emission_affichee"] = (
            emission.strftime("%d/%m/%Y") if emission else None
        )
        item["total_ttc_affiche"] = format_amount(
            item.get("total_ttc"), str(item.get("devise") or "EUR")
        )
        item["est_brouillon"] = (
            str(item.get("libelle_statut") or "").strip().lower() == "brouillon"
        )
        prepared.append(item)
    return prepared


def dashboard_view(request: HttpRequest) -> HttpResponse:
    """Affiche le tableau de bord de l'entreprise active.

    Réservé aux sessions disposant d'une entreprise active (`_guard_entreprise`
    oriente les autres vers l'onboarding ou l'administration des plans). Deux
    appels indépendants alimentent la page — les statistiques agrégées et les
    cinq dernières factures — chacun dégradant séparément : une indisponibilité
    n'affecte que sa propre zone, la page est toujours rendue.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.

    Returns:
        HttpResponse: Rendu du tableau de bord, ou redirection vers le login si
        la session a expiré (ou vers l'espace approprié si aucune entreprise
        n'est active).
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    today = date.today()

    # Statistiques agrégées : fenêtre par défaut de l'API (12 mois glissants).
    try:
        stats = FacturesClient(request).get_statistiques()
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        indicateurs: dict[str, Any] = {}
        stats_disponibles = False
    else:
        indicateurs = _build_indicators(stats, today)
        stats_disponibles = True

    # Activité récente : toutes familles confondues (le badge distingue
    # brouillons et factures émises), les plus récentes d'abord.
    factures_disponibles = True
    try:
        result = FacturesClient(request).list_invoices(limit=_RECENT_INVOICES_LIMIT)
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        factures_recentes: list[dict[str, Any]] = []
        factures_disponibles = False
    else:
        factures_recentes = _prepare_recent_invoices(
            result.get("items") if isinstance(result, dict) else []
        )

    try:
        entreprise_nom = _company_name(request)
    except TokenExpiredError:
        return redirect("login")

    contexte = {
        "entreprise_nom": entreprise_nom,
        "date_du_jour": format_date_fr(today),
        "stats_disponibles": stats_disponibles,
        "factures_disponibles": factures_disponibles,
        "factures_recentes": factures_recentes,
        **indicateurs,
    }
    return render(request, "core/dashboard.html", contexte)
