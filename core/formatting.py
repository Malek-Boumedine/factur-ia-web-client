"""Helpers de formatage à la française, partagés entre les vues.

Les montants du contrat OpenAPI sont des chaînes décimales (« 12480.55 ») et
`LANGUAGE_CODE` vaut « en-us » : le filtre `date` de Django et le formatage
par défaut rendraient dates et nombres en anglais. Tout l'affichage FR
(montants, dates en toutes lettres) est donc préparé côté vue via ce module,
jamais dans les templates.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

# Noms de mois en français, pour les dates en toutes lettres.
MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

# Séparateur de milliers des montants : espace fine insécable (U+202F), usage
# typographique français — un montant ne doit jamais se couper en fin de ligne.
THIN_NBSP = " "


def to_decimal(value: Any) -> Decimal | None:
    """Convertit un montant du contrat (chaîne décimale) en `Decimal`.

    Args:
        value (Any): Valeur brute renvoyée par l'API, possiblement absente ou
            d'une autre forme. Obligatoire.

    Returns:
        Decimal | None: Le montant, ou `None` s'il est absent ou illisible
        (l'affichage retombe alors sur « — »).
    """
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def currency_symbol(devise: Any) -> str:
    """Symbole d'affichage d'une devise (« € » pour EUR, sinon le code brut)."""
    code = str(devise or "EUR").strip().upper()
    return "€" if code == "EUR" else code


def format_amount(value: Any, devise: Any) -> str | None:
    """Formate un montant à la française avec sa devise (ex. « 12 480,00 € »).

    Args:
        value (Any): Montant brut du contrat (chaîne décimale). Obligatoire.
        devise (Any): Code devise ISO 4217 renvoyé par l'API ; « EUR » est
            rendu par son symbole, tout autre code est affiché tel quel.
            Obligatoire.

    Returns:
        str | None: Le montant formaté, ou `None` s'il est illisible (le
        template affiche alors « — »).
    """
    amount = to_decimal(value)
    if amount is None:
        return None
    # Arrondi comptable à deux décimales, puis séparateurs français.
    units, _, decimals = f"{amount.quantize(Decimal('0.01')):,.2f}".partition(".")
    return f"{units.replace(',', THIN_NBSP)},{decimals} {currency_symbol(devise)}"


def format_date_fr(value: date) -> str:
    """Formate une date en toutes lettres à la française (ex. « 28 juillet 2026 »).

    Le 1er du mois prend son ordinal (« 1er juillet »), comme l'usage.
    """
    jour = "1er" if value.day == 1 else str(value.day)
    return f"{jour} {MONTHS_FR[value.month - 1]} {value.year}"


def parse_iso_date(value: Any) -> date | None:
    """Convertit une date ISO du contrat en `date`, `None` si absente ou illisible."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None
