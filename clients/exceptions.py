"""Exceptions métier centralisées pour la couche `clients/`.

Toute la couche cliente (`BaseAPIClient` et ses sous-classes) traduit les
réponses HTTP et les incidents réseau de `httpx` en exceptions de ce module.
Les vues Django et les clients enfants n'attrapent donc QUE ces exceptions,
jamais des codes HTTP bruts ni des exceptions `httpx`.

Hiérarchie :

    APIClientError                (base commune)
    ├── TokenExpiredError         (401, authentification expirée/invalide)
    ├── ResourceNotFoundError     (404, ressource introuvable)
    ├── APIValidationError        (422, validation — conserve le détail)
    ├── ServerError               (5xx, erreur côté serveur)
    └── APIUnavailableError       (API injoignable après épuisement des retries)
"""

from typing import Any


class APIClientError(Exception):
    """Exception de base de toutes les erreurs de la couche cliente API.

    Attributes:
        message (str): Message d'erreur lisible.
        status_code (int | None): Code HTTP à l'origine de l'erreur, si connu
            (`None` pour un incident réseau sans réponse).
    """

    def __init__(
        self,
        message: str = "Erreur de communication avec l'API.",
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TokenExpiredError(APIClientError):
    """Authentification expirée ou invalide (HTTP 401).

    Levée après avoir vidé la session Django. Les vues l'interceptent pour
    rediriger l'utilisateur vers la page de connexion.
    """

    def __init__(self, message: str = "Token expiré ou invalide.") -> None:
        super().__init__(message, status_code=401)


class ResourceNotFoundError(APIClientError):
    """Ressource introuvable (HTTP 404)."""

    def __init__(self, message: str = "Ressource introuvable.") -> None:
        super().__init__(message, status_code=404)


class APIValidationError(APIClientError):
    """Erreur de validation renvoyée par l'API (HTTP 422).

    Conserve le détail du corps `HTTPValidationError` du contrat OpenAPI (champ
    `detail` : liste d'objets `{loc, msg, type, ...}`) afin de pouvoir rattacher
    les erreurs aux champs d'un formulaire Django.

    Attributes:
        detail (Any): Contenu du champ `detail` de la réponse 422 (liste des
            erreurs de validation), ou `None` si le corps n'est pas exploitable.
    """

    def __init__(self, detail: Any = None, message: str = "Données invalides.") -> None:
        super().__init__(message, status_code=422)
        self.detail = detail


class ServerError(APIClientError):
    """Erreur côté serveur de l'API (HTTP 5xx non transitoire, ex. 500).

    Les codes transitoires 502/503/504 ne remontent PAS ici lorsqu'ils
    concernent une requête idempotente : ils sont rejoués puis, en cas d'échec
    persistant, convertis en `APIUnavailableError`.
    """

    def __init__(
        self,
        message: str = "Erreur interne du serveur API.",
        *,
        status_code: int | None = 500,
    ) -> None:
        super().__init__(message, status_code=status_code)


class APIUnavailableError(APIClientError):
    """API injoignable après épuisement des tentatives.

    Levée lorsqu'un timeout, une erreur réseau (connexion/lecture) ou un code
    transitoire (502/503/504) persiste après le nombre maximal de tentatives
    de rejeu.
    """

    def __init__(
        self,
        message: str = "Service API momentanément indisponible.",
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
