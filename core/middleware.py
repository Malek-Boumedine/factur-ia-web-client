"""Middlewares du BFF.

`SessionExpiryMiddleware` maintient la cohérence entre la session Django et la
validité réelle du JWT de l'API : sans lui, une session peut rester marquée
« connectée » (cookie valable 14 jours par défaut) alors que le token qu'elle
porte est périmé depuis longtemps. L'expiration n'était alors détectée qu'au
premier 401 renvoyé par l'API (`clients.base_client`) — donc jamais sur les
pages qui n'appellent aucune route protégée, comme l'accueil, qui s'affichait
dans son état connecté à tort.
"""

import base64
import binascii
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse

# Libellé aligné sur celui du 401 (`clients.base_client._map_response`) : que
# l'expiration soit détectée en amont ici ou par l'API, l'utilisateur lit le
# même message.
_MSG_SESSION_EXPIREE = "Votre session a expiré. Veuillez vous reconnecter."


def _decode_jwt_payload(token: Any) -> dict[str, Any] | None:
    """Décode la charge utile d'un JWT sans vérifier sa signature.

    Un JWT est composé de trois segments base64url séparés par des points ; le
    deuxième porte les claims en JSON. On se contente de le lire : vérifier la
    signature est impossible côté BFF (le secret appartient à l'API) et inutile
    ici, car ce token n'a jamais transité par le navigateur — il vient de l'API
    et vit dans une session serveur (Redis). L'API reste l'autorité : un token
    accepté ici mais révoqué chez elle sera rejeté par un 401.

    Args:
        token (Any): Valeur lue en session (`jwt_token`). Peut être `None` ou
            de type inattendu : la fonction ne fait jamais confiance à l'entrée.

    Returns:
        dict | None: Les claims décodés, ou `None` si la valeur n'est pas un
        JWT exploitable (absente, mal formée, base64 ou JSON invalide).
    """
    if not isinstance(token, str):
        return None
    segments = token.split(".")
    if len(segments) != 3:
        return None
    payload = segments[1]
    # Le base64url d'un JWT est émis sans padding : on le rétablit.
    payload += "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def get_token_expiry(token: Any) -> datetime | None:
    """Renvoie la date d'expiration (`exp`) d'un JWT, en UTC.

    Args:
        token (Any): Valeur lue en session (`jwt_token`). Obligatoire, mais
            tolère `None` et les valeurs mal formées.

    Returns:
        datetime | None: L'instant d'expiration en UTC, ou `None` si le token
        est illisible ou ne porte pas de claim `exp` numérique exploitable.
        Dans ce cas l'appelant ne doit rien conclure : on ne déconnecte jamais
        sur une simple absence d'information.
    """
    claims = _decode_jwt_payload(token)
    if claims is None:
        return None
    exp = claims.get("exp")
    # `bool` est un `int` : on l'exclut explicitement, ce n'est pas une date.
    if isinstance(exp, bool) or not isinstance(exp, int | float):
        return None
    try:
        return datetime.fromtimestamp(exp, UTC)
    except (OverflowError, OSError, ValueError):
        # Valeur hors des bornes représentables : token inexploitable.
        return None


class SessionExpiryMiddleware:
    """Purge la session dès que le JWT qu'elle porte est expiré.

    Le BFF n'utilise pas `django.contrib.auth` : l'état de connexion est la clé
    de session `is_authenticated`, lue telle quelle par les templates
    (en-tête, accueil, tableau de bord) et par les gardes des vues protégées.
    Cette clé est donc la source de vérité unique — vider la session ici suffit
    à rendre l'état cohérent partout, sans toucher ni aux vues ni aux templates :
    les pages publiques repassent en affichage déconnecté, les pages protégées
    redirigent vers la connexion par leurs gardes existants.

    Doit être déclaré **après** `MessageMiddleware` dans `MIDDLEWARE` : la phase
    requête s'exécute de haut en bas et l'ajout d'un message nécessite que ce
    dernier ait déjà installé le stockage sur la requête.

    Prudence volontaire : la session n'est purgée que si le token porte un `exp`
    exploitable et strictement dépassé. Un token illisible ou sans `exp` laisse
    la session intacte — le 401 de la couche cliente reste le filet de sécurité.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self._purge_si_expiree(request)
        return self.get_response(request)

    @staticmethod
    def _purge_si_expiree(request: HttpRequest) -> None:
        """Vide la session et prévient l'utilisateur si son JWT est périmé.

        Args:
            request (HttpRequest): Requête Django courante. Obligatoire.
        """
        session = request.session
        if not session.get("is_authenticated"):
            return

        expiry = get_token_expiry(session.get("jwt_token"))
        if expiry is None or expiry > datetime.now(UTC):
            return

        # Même séquence que le traitement du 401 : la session est d'abord vidée
        # (`flush` en ouvre une nouvelle, vierge), le message est déposé ensuite
        # pour survivre à la purge et s'afficher au rendu de la page demandée.
        session.flush()
        messages.error(request, _MSG_SESSION_EXPIREE)
