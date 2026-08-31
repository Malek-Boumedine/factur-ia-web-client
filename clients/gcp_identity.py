"""Jeton d'identité Google pour l'authentification IAM de Cloud Run.

En production, l'API data n'est pas publique : Cloud Run n'accepte que les
appels portant un jeton d'identité Google d'un compte autorisé
(`roles/run.invoker`). L'en-tête `Authorization` transportant déjà le JWT
applicatif de l'utilisateur, le jeton d'identité voyage dans
`X-Serverless-Authorization`, prévu par Cloud Run pour ce cas précis (la
plateforme le vérifie puis le retire avant de transmettre la requête).

Le jeton est obtenu via `google-auth` auprès du serveur de métadonnées de
Cloud Run (aucune clé), avec pour audience l'URL du service appelé
(`API_DATA_URL`). Valable une heure, il est mis en cache au niveau du module
et renouvelé avec une marge d'avance ; l'accès est verrouillé car Gunicorn
sert plusieurs requêtes par worker via des threads.

Interrupteur : `API_IAM_AUTH_ENABLED` (défaut faux). Hors production (dev,
test), le module ne fait strictement rien — pas de serveur de métadonnées en
local, et l'API locale n'exige aucun jeton.
"""

import base64
import binascii
import json
import logging
import threading
import time

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.id_token import fetch_id_token

from .exceptions import APIUnavailableError

logger = logging.getLogger("clients.gcp_identity")

# Marge de renouvellement : un jeton à moins de 5 minutes de son expiration
# est considéré périmé, pour ne jamais envoyer un jeton mourant en vol.
_REFRESH_MARGIN = 300.0

# Durée de vie supposée (une heure, standard Google) si la claim `exp` du
# jeton reçu s'avère illisible — cas théorique, on reste défensif.
_FALLBACK_LIFETIME = 3600.0

# Cache module-niveau : partagé par tous les threads d'un worker Gunicorn.
_lock = threading.Lock()
_cached_token: str | None = None
_cached_expiry = 0.0  # epoch (secondes), 0 = aucun jeton en cache


def serverless_authorization_header() -> dict[str, str]:
    """Construit l'en-tête d'authentification IAM Cloud Run, si activé.

    Point d'entrée unique du module, appelé par `BaseAPIClient` à chaque
    construction d'en-têtes. Quand `API_IAM_AUTH_ENABLED` est faux (dev,
    test), renvoie un dictionnaire vide sans la moindre tentative
    d'obtention de jeton.

    Returns:
        dict[str, str]: `{"X-Serverless-Authorization": "Bearer <jeton>"}`
        si l'authentification IAM est activée, `{}` sinon.

    Raises:
        APIUnavailableError: Jeton impossible à obtenir alors que
            l'authentification IAM est activée (l'API est de fait
            injoignable ; les vues savent déjà traiter ce cas).
    """
    if not getattr(settings, "API_IAM_AUTH_ENABLED", False):
        return {}
    return {"X-Serverless-Authorization": f"Bearer {_get_identity_token()}"}


def _get_identity_token() -> str:
    """Renvoie un jeton d'identité valide, depuis le cache ou fraîchement obtenu.

    Le verrou couvre la lecture ET le renouvellement : un seul thread
    interroge le serveur de métadonnées, les autres attendent le jeton frais
    plutôt que de déclencher des obtentions concurrentes.

    Returns:
        str: Jeton d'identité Google encore valide au moins `_REFRESH_MARGIN`
        secondes.

    Raises:
        APIUnavailableError: Échec de l'obtention auprès du serveur de
            métadonnées.
    """
    global _cached_token, _cached_expiry
    with _lock:
        now = time.time()
        if _cached_token is not None and now < _cached_expiry - _REFRESH_MARGIN:
            return _cached_token

        token = _fetch_identity_token()
        _cached_token = token
        _cached_expiry = _read_expiry(token, now)
        return token


def _fetch_identity_token() -> str:
    """Obtient un jeton d'identité auprès du serveur de métadonnées Cloud Run.

    L'audience est l'URL du service appelé (`API_DATA_URL`) : c'est elle que
    Cloud Run vérifie côté API data. Aucune clé ni fichier de credentials :
    `google-auth` s'appuie sur l'identité du compte de service du conteneur.

    Returns:
        str: Jeton d'identité (JWT signé par Google), valable une heure.

    Raises:
        APIUnavailableError: Toute erreur d'obtention (serveur de métadonnées
            injoignable, identité absente) — journalisée puis traduite dans
            l'exception que les vues savent traiter.
    """
    audience = settings.API_DATA_URL
    try:
        return fetch_id_token(Request(), audience)
    except Exception as exc:
        logger.error(
            "Échec d'obtention du jeton d'identité Google (audience %s) : %s",
            audience,
            exc,
        )
        raise APIUnavailableError() from exc


def _read_expiry(token: str, now: float) -> float:
    """Lit l'expiration (`exp`) dans le payload du jeton, sans vérification.

    Le jeton vient d'être remis par le serveur de métadonnées : aucune raison
    de vérifier sa signature, on ne fait que planifier son renouvellement.

    Args:
        token (str): Jeton d'identité au format JWT. Obligatoire.
        now (float): Horodatage courant (epoch), base du repli si la claim
            est illisible. Obligatoire.

    Returns:
        float: Expiration en secondes epoch — la claim `exp`, ou
        `now + _FALLBACK_LIFETIME` si elle est illisible.
    """
    try:
        payload_b64 = token.split(".")[1]
        # Le base64url des JWT est émis sans padding : on le complète.
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload["exp"])
    except (IndexError, KeyError, TypeError, ValueError, binascii.Error):
        logger.warning("Claim `exp` illisible dans le jeton d'identité, repli 1 h.")
        return now + _FALLBACK_LIFETIME
