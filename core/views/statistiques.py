"""Vue de la page Statistiques (synthèse chiffrée sur période choisie).

Complément analytique du tableau de bord : là où le tableau de bord fige le
mois en cours (KPI d'atterrissage + raccourcis), cette page laisse choisir la
période et détaille les totaux de GET /factures/statistiques — chiffre
d'affaires HT/TTC, TVA collectée, panier moyen, volumes, encours.

La période vit dans l'URL (`?periode=<clé>`, plus `date_min`/`date_max` en
mode personnalisé) : la page est partageable et rechargeable. Les bornes sont
résolues côté vue puis transmises à l'API ; la période affichée est celle que
l'API a réellement appliquée (champ `periode` de la réponse), jamais celle
demandée.

Un seul appel réseau, aucun calcul de montant côté front : les agrégations
sont faites en SQL par l'API (chiffres exacts sans pagination). Les
visualisations détaillées (évolution mensuelle, répartition par statut,
meilleurs clients) sont des barres CSS pur : la vue pré-calcule les
proportions (max de la série = 100 %) et le template ne fait que poser des
largeurs — aucune librairie de graphiques, aucun appel supplémentaire.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.exceptions import APIClientError, TokenExpiredError
from clients.factures_client import FacturesClient
from core.formatting import (
    MONTHS_FR,
    format_amount,
    format_date_fr,
    parse_iso_date,
    to_decimal,
)
from core.views.auth import _guard_entreprise
from core.views.factures import _STATUS_BADGES

# Clé du mode libre : les bornes viennent des champs date_min/date_max.
_CUSTOM_PERIOD = "personnalise"

# Période par défaut : 12 mois glissants, la même fenêtre que le défaut de
# l'API et que le tableau de bord — même chiffre des deux côtés à l'arrivée.
_DEFAULT_PERIOD = "12-mois"

# Couleur de remplissage des barres de la répartition par statut, dérivée de
# la famille du badge (`_STATUS_BADGES`) : un statut garde la même couleur en
# badge dans les listes et en barre dans les statistiques.
_BADGE_TO_BAR = {
    "badge-ghost": "bg-base-300",
    "badge-neutral": "bg-neutral",
    "badge-info": "bg-info",
    "badge-success": "bg-success",
    "badge-warning": "bg-warning",
    "badge-error": "bg-error",
}

# Largeur minimale (en %) d'une barre de valeur positive : face au maximum de
# la série, une petite valeur reste visible au lieu de disparaître.
_MIN_BAR_PERCENT = 2

# Nombre de clients affichés dans le classement des meilleurs clients.
_TOP_CLIENTS_LIMIT = 5


def _bar_percent(value: Decimal | int, maximum: Decimal | int) -> int:
    """Largeur d'une barre en pourcentage du maximum de sa série.

    Valeur nulle ou négative (un mois où les avoirs dépassent les factures) →
    0, pas de barre : la valeur reste lisible en texte. Valeur positive → au
    moins `_MIN_BAR_PERCENT`. Maximum nul ou négatif → 0 partout (série vide
    de sens, aucune division par zéro).

    Args:
        value (Decimal | int): Valeur de l'élément courant. Obligatoire.
        maximum (Decimal | int): Maximum de la série. Obligatoire.

    Returns:
        int: Largeur en pourcentage, entre 0 et 100.
    """
    if value <= 0 or maximum <= 0:
        return 0
    return max(_MIN_BAR_PERCENT, round(value * 100 / maximum))


def _month_label(value: Any) -> str | None:
    """Libellé FR d'un mois du contrat (« 2026-01 » → « janvier 2026 »).

    Args:
        value (Any): Champ `mois` du contrat (attendu « YYYY-MM »).
            Obligatoire.

    Returns:
        str | None: Le libellé, ou `None` si le champ est illisible.
    """
    year, _, month = str(value or "").partition("-")
    if not (year.isdigit() and month.isdigit() and 1 <= int(month) <= 12):
        return None
    return f"{MONTHS_FR[int(month) - 1]} {year}"


def _build_monthly_chart(stats: dict[str, Any], devise: str) -> list[dict[str, Any]]:
    """Prépare les barres d'évolution mensuelle du CA TTC.

    L'API renvoie une série continue (mois vides à zéro) : si toute la série
    est à zéro, la liste rendue est vide et le template affiche « aucune
    donnée » plutôt que d'aligner des barres nulles. Lecture défensive : un
    mois malformé est ignoré, jamais un plantage.

    Args:
        stats (dict[str, Any]): Réponse de GET /factures/statistiques.
            Obligatoire.
        devise (str): Devise des montants agrégés. Obligatoire.

    Returns:
        list[dict[str, Any]]: Un item par mois — libellé FR, montant formaté,
        largeur de barre en pourcentage du meilleur mois.
    """
    source = stats.get("par_mois")
    rows: list[dict[str, Any]] = []
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict):
            continue
        label = _month_label(item.get("mois"))
        montant = to_decimal(item.get("ca_ttc"))
        if label is None or montant is None:
            continue
        nombre = item.get("nombre")
        rows.append(
            {
                "label": label,
                "value": montant,
                "montant": format_amount(montant, devise),
                "nombre": nombre if isinstance(nombre, int) else 0,
            }
        )
    if not any(row["value"] or row["nombre"] for row in rows):
        return []
    maximum = max(row["value"] for row in rows)
    for row in rows:
        row["pct"] = _bar_percent(row.pop("value"), maximum)
    return rows


def _build_status_chart(stats: dict[str, Any], devise: str) -> list[dict[str, Any]]:
    """Prépare les barres de répartition par statut.

    La longueur est proportionnelle au nombre de documents, pas au montant :
    c'est la lecture naturelle d'une répartition, et un montant peut être
    négatif (statut neutralisé par ses avoirs) — il reste affiché en texte.
    Tri du statut le plus fréquent au moins fréquent ; statut inconnu du
    référentiel → libellé brut sur barre neutre, l'affichage ne casse jamais.

    Args:
        stats (dict[str, Any]): Réponse de GET /factures/statistiques.
            Obligatoire.
        devise (str): Devise des montants agrégés. Obligatoire.

    Returns:
        list[dict[str, Any]]: Un item par statut — libellé FR, classes du
        badge et de la barre (couleurs cohérentes), nombre, montant formaté,
        largeur en pourcentage du statut le plus fréquent.
    """
    source = stats.get("par_statut")
    rows: list[dict[str, Any]] = []
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("statut") or "").strip()
        nombre = item.get("nombre")
        if not raw or not isinstance(nombre, int):
            continue
        label, badge = _STATUS_BADGES.get(raw.lower(), (raw, "badge-ghost"))
        rows.append(
            {
                "label": label,
                "badge": badge,
                "bar": _BADGE_TO_BAR.get(badge.split()[0], "bg-base-300"),
                "nombre": nombre,
                "montant": format_amount(item.get("montant_ttc"), devise),
            }
        )
    if not rows:
        return []
    rows.sort(key=lambda row: row["nombre"], reverse=True)
    maximum = max(row["nombre"] for row in rows)
    for row in rows:
        row["pct"] = _bar_percent(row["nombre"], maximum)
    return rows


def _build_top_clients(stats: dict[str, Any], devise: str) -> list[dict[str, Any]]:
    """Prépare les barres des meilleurs clients (limitées à 5).

    L'ordre du contrat (CA TTC décroissant) est conservé. Un client sans
    fiche rattachée (`nom_client` null) est regroupé sous « Sans client
    rattaché ». Lecture défensive : item malformé ignoré.

    Args:
        stats (dict[str, Any]): Réponse de GET /factures/statistiques.
            Obligatoire.
        devise (str): Devise des montants agrégés. Obligatoire.

    Returns:
        list[dict[str, Any]]: Un item par client — nom, montant formaté,
        nombre de documents, largeur en pourcentage du meilleur client.
    """
    source = stats.get("top_clients")
    rows: list[dict[str, Any]] = []
    for item in (source if isinstance(source, list) else [])[:_TOP_CLIENTS_LIMIT]:
        if not isinstance(item, dict):
            continue
        montant = to_decimal(item.get("ca_ttc"))
        if montant is None:
            continue
        nombre = item.get("nombre")
        rows.append(
            {
                "nom": str(item.get("nom_client") or "").strip()
                or "Sans client rattaché",
                "value": montant,
                "montant": format_amount(montant, devise),
                "nombre": nombre if isinstance(nombre, int) else 0,
            }
        )
    if not rows:
        return []
    maximum = max(row["value"] for row in rows)
    for row in rows:
        row["pct"] = _bar_percent(row.pop("value"), maximum)
    return rows


def _month_start(day: date) -> date:
    """Premier jour du mois de `day`."""
    return day.replace(day=1)


def _quarter_start(day: date) -> date:
    """Premier jour du trimestre civil de `day`."""
    return day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)


def _year_start(day: date) -> date:
    """Premier janvier de l'année de `day`."""
    return day.replace(month=1, day=1)


def _previous_month_bounds(day: date) -> tuple[date, date]:
    """Bornes (1er, dernier jour) du mois précédant celui de `day`."""
    end = _month_start(day) - timedelta(days=1)
    return _month_start(end), end


def _rolling_year_start(day: date) -> date:
    """Premier jour du mois, 11 mois avant `day` (fenêtre 12 mois glissants)."""
    months = day.year * 12 + (day.month - 1) - 11
    return date(months // 12, months % 12 + 1, 1)


# Périodes proposées par le sélecteur : clé d'URL -> (libellé du bouton,
# fonction (aujourd'hui) -> bornes (date_min, date_max)). L'ordre est celui
# d'affichage ; le mode personnalisé est géré à part (bornes saisies).
_PERIODS: dict[str, tuple[str, Any]] = {
    "mois": ("Ce mois", lambda today: (_month_start(today), today)),
    "mois-precedent": ("Mois dernier", _previous_month_bounds),
    "trimestre": ("Ce trimestre", lambda today: (_quarter_start(today), today)),
    "annee": ("Cette année", lambda today: (_year_start(today), today)),
    _DEFAULT_PERIOD: (
        "12 derniers mois",
        lambda today: (_rolling_year_start(today), today),
    ),
}


def _resolve_period(
    request: HttpRequest, today: date
) -> tuple[str, date, date, str | None]:
    """Résout la période demandée par l'URL en bornes de dates.

    Clé inconnue → période par défaut. Mode personnalisé : les deux dates
    doivent être lisibles, sinon repli sur la période par défaut avec un
    message ; des bornes inversées sont réordonnées silencieusement
    (l'intention est évidente, inutile d'échouer).

    Args:
        request (HttpRequest): Requête Django courante (query params `periode`,
            `date_min`, `date_max`). Obligatoire.
        today (date): Date du jour, référence des périodes relatives.
            Obligatoire.

    Returns:
        tuple: (clé de période effective, date_min, date_max, message
        d'avertissement ou `None`).
    """
    key = request.GET.get("periode", _DEFAULT_PERIOD)

    if key == _CUSTOM_PERIOD:
        date_min = parse_iso_date(request.GET.get("date_min"))
        date_max = parse_iso_date(request.GET.get("date_max"))
        if date_min and date_max:
            if date_min > date_max:
                date_min, date_max = date_max, date_min
            return key, date_min, date_max, None
        warning = (
            "Renseignez les deux dates de la période personnalisée — "
            "affichage des 12 derniers mois en attendant."
        )
        start, end = _PERIODS[_DEFAULT_PERIOD][1](today)
        return _DEFAULT_PERIOD, start, end, warning

    if key not in _PERIODS:
        key = _DEFAULT_PERIOD
    start, end = _PERIODS[key][1](today)
    return key, start, end, None


def _build_summary(stats: Any) -> dict[str, Any]:
    """Prépare les chiffres de synthèse depuis la réponse de l'API.

    Tous les montants sont formatés à la française côté vue (le template
    n'effectue aucun calcul). Lecture défensive : toute partie absente ou
    malformée retombe sur `None` (affiché « — »), jamais un plantage.

    Args:
        stats (Any): Réponse de GET /factures/statistiques (schéma
            StatistiquesFactures). Obligatoire.

    Returns:
        dict[str, Any]: Entrées de contexte des cartes de synthèse, des
        visualisations en barres, de la période appliquée et des notes de
        lecture.
    """
    if not isinstance(stats, dict):
        stats = {}
    devise = str(stats.get("devise") or "EUR")

    totaux = stats.get("totaux") if isinstance(stats.get("totaux"), dict) else {}
    paiement = stats.get("paiement") if isinstance(stats.get("paiement"), dict) else {}
    brouillons = (
        stats.get("brouillons") if isinstance(stats.get("brouillons"), dict) else {}
    )

    nombre_factures = totaux.get("nombre_factures")
    nombre_avoirs = totaux.get("nombre_avoirs")
    brouillons_nombre = brouillons.get("nombre")

    exclues = stats.get("devises_exclues")
    devises_exclues = [
        item
        for item in (exclues if isinstance(exclues, list) else [])
        if isinstance(item, dict) and item.get("devise")
    ]

    # Période réellement agrégée : c'est l'API qui fait foi, pas la demande.
    periode = stats.get("periode") if isinstance(stats.get("periode"), dict) else {}
    periode_debut = parse_iso_date(periode.get("date_min"))
    periode_fin = parse_iso_date(periode.get("date_max"))

    # Aucun document sur la période (ni émis, ni brouillon) : la page invite
    # à élargir la période plutôt que d'aligner des zéros sans explication.
    counts = (nombre_factures, nombre_avoirs, brouillons_nombre)
    periode_vide = all(isinstance(c, int) for c in counts) and not any(counts)

    return {
        "devise_code": devise,
        "ca_ht": format_amount(totaux.get("ca_ht"), devise),
        "ca_ttc": format_amount(totaux.get("ca_ttc"), devise),
        "tva_collectee": format_amount(totaux.get("tva_collectee"), devise),
        "panier_moyen": format_amount(totaux.get("panier_moyen"), devise),
        "nombre_factures": (
            nombre_factures if isinstance(nombre_factures, int) else None
        ),
        "nombre_avoirs": nombre_avoirs if isinstance(nombre_avoirs, int) else None,
        "restant_a_encaisser": format_amount(
            paiement.get("restant_a_encaisser"), devise
        ),
        "montant_en_retard": format_amount(paiement.get("montant_en_retard"), devise),
        "brouillons_nombre": (
            brouillons_nombre if isinstance(brouillons_nombre, int) else None
        ),
        "brouillons_montant": format_amount(brouillons.get("montant_ttc"), devise),
        "devises_exclues": devises_exclues,
        "periode_debut": format_date_fr(periode_debut) if periode_debut else None,
        "periode_fin": format_date_fr(periode_fin) if periode_fin else None,
        "periode_vide": periode_vide,
        "chart_mois": _build_monthly_chart(stats, devise),
        "chart_statuts": _build_status_chart(stats, devise),
        "chart_clients": _build_top_clients(stats, devise),
    }


def statistiques_view(request: HttpRequest) -> HttpResponse:
    """Affiche les statistiques de facturation sur la période choisie.

    Réservée aux sessions avec entreprise active (`_guard_entreprise`). La
    période de l'URL est résolue en bornes, transmises à
    GET /factures/statistiques ; la synthèse affiche les totaux exacts
    calculés en SQL par l'API. API indisponible : le sélecteur reste rendu et
    fonctionnel, seuls les chiffres laissent place à un message local.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.

    Returns:
        HttpResponse: Rendu de la page, ou redirection vers le login si la
        session a expiré (ou vers l'espace approprié sans entreprise active).
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    today = date.today()
    period_key, date_min, date_max, period_warning = _resolve_period(request, today)

    try:
        stats = FacturesClient(request).get_statistiques(
            date_min=date_min.isoformat(), date_max=date_max.isoformat()
        )
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        synthese: dict[str, Any] = {}
        stats_disponibles = False
    else:
        synthese = _build_summary(stats)
        stats_disponibles = True

    # Boutons du sélecteur : (clé, libellé, active) dans l'ordre d'affichage.
    period_choices = [
        (key, label, key == period_key) for key, (label, _) in _PERIODS.items()
    ]

    contexte = {
        "periode_cle": period_key,
        "periode_personnalisee": request.GET.get("periode") == _CUSTOM_PERIOD,
        "periode_choix": period_choices,
        "periode_warning": period_warning,
        # Valeurs des champs du formulaire personnalisé : bornes effectives,
        # pré-remplies aussi en mode preset (point de départ d'un ajustement).
        "date_min": date_min.isoformat(),
        "date_max": date_max.isoformat(),
        "stats_disponibles": stats_disponibles,
        **synthese,
    }
    return render(request, "core/statistiques.html", contexte)
