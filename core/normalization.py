"""Normalisation des identifiants saisis, partagée entre vues et formulaires.

Un SIREN/SIRET est couramment recopié avec des séparateurs (« 123 456 789
00012 », points ou tirets d'un extrait Kbis, espaces insécables d'un PDF) :
la normalisation doit s'appliquer avant tout contrôle de longueur ou de
format, et la valeur envoyée à l'API est toujours la version normalisée.
Source unique — même logique que la normalisation côté API.
"""

from typing import Any


def normalize_siret(value: Any) -> str:
    """Normalise un SIREN/SIRET saisi : blancs Unicode, points et tirets retirés.

    `str.isspace()` couvre tous les blancs Unicode (espace, insécable U+00A0,
    fine U+2009, fine insécable U+202F, tabulation…) sans liste à maintenir.

    Args:
        value (Any): Valeur brute saisie, possiblement absente. Obligatoire.

    Returns:
        str: Identifiant nettoyé (chaîne vide si absent).
    """
    return "".join(ch for ch in str(value or "") if not ch.isspace() and ch not in ".-")
