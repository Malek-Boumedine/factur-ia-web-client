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
sont faites en SQL par l'API (chiffres exacts sans pagination). Les sections
de visualisations détaillées (évolution mensuelle, répartition par statut,
meilleurs clients) sont réservées dans le template — la réponse les contient
déjà, elles seront branchées dans une tâche ultérieure sans appel
supplémentaire.
"""

from datetime import date, timedelta
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.exceptions import APIClientError, TokenExpiredError
from clients.factures_client import FacturesClient
from core.formatting import format_amount, format_date_fr, parse_iso_date
from core.views.auth import _guard_entreprise

# Clé du mode libre : les bornes viennent des champs date_min/date_max.
_CUSTOM_PERIOD = "personnalise"

# Période par défaut : 12 mois glissants, la même fenêtre que le défaut de
# l'API et que le tableau de bord — même chiffre des deux côtés à l'arrivée.
_DEFAULT_PERIOD = "12-mois"


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
        dict[str, Any]: Entrées de contexte des cartes de synthèse, de la
        période appliquée et des notes de lecture.
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
