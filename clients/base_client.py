"""Socle commun des clients HTTP vers l'API FastAPI (`API_DATA_URL`).

Ce module fournit :

- `BaseAPIClient` : classe parente dont héritent tous les clients métier
  (`ClientsClient`, `ProduitsClient`, `FacturesClient`, `AbonnementsClient`,
  `DocumentsClient`, `UtilisateursClient`). Elle centralise la construction des
  en-têtes (JWT + tenant `x-entreprise-id`), l'émission des requêtes `httpx`
  (GET/POST/PUT/PATCH/DELETE + upload multipart), la **résilience réseau**
  (timeouts explicites, retries avec backoff exponentiel) et le **mapping** des
  réponses vers les exceptions métier de `clients.exceptions`.

`TokenExpiredError` est ré-exporté ici pour compatibilité avec les imports
existants (`from clients.base_client import TokenExpiredError`) ; sa définition
vit désormais dans `clients.exceptions`.

Ce fichier ne cible aucune route métier précise : il expose les primitives HTTP
réutilisées par les sous-classes, qui portent, elles, les chemins du contrat.
"""

import logging
import time
from typing import Any

import httpx
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest

from .exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    ServerError,
    TokenExpiredError,
)

# Ré-export pour compatibilité ascendante (anciens imports depuis ce module).
__all__ = ["BaseAPIClient", "TokenExpiredError"]

logger = logging.getLogger("clients.base_client")

# Codes serveur considérés comme transitoires : seuls ceux-ci sont rejoués
# (uniquement pour les méthodes idempotentes). 500/501 ne sont PAS rejoués.
_RETRYABLE_STATUS = {502, 503, 504}

# Valeurs par défaut si les settings ne les définissent pas (résilience).
_DEFAUT_CONNECT_TIMEOUT = 5.0
_DEFAUT_READ_TIMEOUT = 15.0
_DEFAUT_MAX_RETRIES = 2
_DEFAUT_RETRY_BACKOFF = 0.5


class BaseAPIClient:
    """Client parent pour toutes les requêtes vers l'API FastAPI.

    Injecte le JWT et gère la déconnexion forcée en cas d'expiration.

    Toutes les sous-classes héritent de cette classe et réutilisent ses méthodes
    HTTP (`get`, `post`, `put`, `patch`, `delete`, `post_file`) ; elles ne
    doivent jamais appeler `httpx` directement, ni manipuler de codes HTTP bruts.
    L'authentification (Bearer JWT) et le contexte multi-tenant
    (`x-entreprise-id`) sont résolus depuis la session Django et injectés
    automatiquement dans les en-têtes.

    Résilience : chaque requête applique un timeout explicite (connexion vs
    lecture, lus depuis les settings) ; les erreurs transitoires (timeout,
    erreur réseau, 502/503/504) des méthodes idempotentes sont rejouées avec un
    backoff exponentiel avant de lever `APIUnavailableError`. Toutes les
    réponses d'erreur sont traduites en exceptions de `clients.exceptions`.

    Attributes:
        request (HttpRequest): La requête Django courante, source de la session
            contenant le JWT et l'identifiant d'entreprise.
        base_url (str): URL de base de l'API, issue de `settings.API_DATA_URL`.
    """

    def __init__(self, request: HttpRequest) -> None:
        """Initialise le client à partir de la requête Django courante.

        Args:
            request (HttpRequest): Requête Django en cours. Sa session fournit
                `jwt_token` et `entreprise_id` utilisés pour l'auth et le
                contexte tenant. Obligatoire.
        """
        self.request = request
        self.base_url = settings.API_DATA_URL

        # Politique de résilience, configurable via les settings Django.
        # Timeout httpx distinguant connexion et lecture (write/pool = lecture).
        self._timeout = httpx.Timeout(
            getattr(settings, "API_READ_TIMEOUT", _DEFAUT_READ_TIMEOUT),
            connect=getattr(settings, "API_CONNECT_TIMEOUT", _DEFAUT_CONNECT_TIMEOUT),
        )
        self._max_retries = getattr(settings, "API_MAX_RETRIES", _DEFAUT_MAX_RETRIES)
        self._retry_backoff = getattr(
            settings, "API_RETRY_BACKOFF", _DEFAUT_RETRY_BACKOFF
        )

    @property
    def auth_headers(self) -> dict[str, str]:
        """En-têtes d'authentification (sans Content-Type, pour le multipart).

        Construit les en-têtes minimaux : `Accept`, plus `Authorization` si un
        JWT est présent en session et `x-entreprise-id` si une entreprise active
        est connue. Utilisé tel quel pour les uploads multipart (où httpx doit
        calculer lui-même le Content-Type).

        Returns:
            dict[str, str]: En-têtes HTTP. Contient toujours `Accept` ;
            `Authorization` et `x-entreprise-id` sont ajoutés seulement s'ils
            sont disponibles en session.
        """
        headers = {
            "Accept": "application/json",
        }

        token = self.request.session.get("jwt_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # On injecte l'ID de l'entreprise (le Tenant)
        entreprise_id = self.request.session.get("entreprise_id")
        if entreprise_id:
            headers["x-entreprise-id"] = str(entreprise_id)

        return headers

    @property
    def headers(self) -> dict[str, str]:
        """Construit les en-têtes JSON avec le token et l'ID de l'entreprise.

        Reprend `auth_headers` et y ajoute `Content-Type: application/json`.
        Utilisé pour toutes les requêtes à corps JSON (GET/POST/PUT/PATCH/DELETE).

        Returns:
            dict[str, str]: En-têtes de `auth_headers` enrichis du
            `Content-Type` JSON.
        """
        return {**self.auth_headers, "Content-Type": "application/json"}

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        idempotent: bool,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> httpx.Response:
        """Émet une requête httpx avec timeout et rejeu des erreurs transitoires.

        Choix d'implémentation : une boucle de rejeu maison (ni tenacity ni le
        transport httpx). Le transport httpx ne rejoue que les erreurs de
        connexion, pas les statuts 502/503/504 ; et la condition de rejeu dépend
        ici de l'idempotence de la méthode ET du statut/exception, ce qui se
        gère plus simplement et sans dépendance supplémentaire par une boucle
        explicite (qui journalise aussi chaque tentative).

        Ne rejoue QUE les erreurs transitoires (timeout, erreur réseau,
        502/503/504) et UNIQUEMENT pour les méthodes idempotentes ; jamais un
        POST de création ni une erreur 4xx.

        Args:
            method (str): Méthode HTTP (GET, POST, ...). Obligatoire.
            endpoint (str): Chemin concaténé à `base_url`. Obligatoire.
            idempotent (bool): Autorise le rejeu si `True`. Obligatoire.
            headers (dict[str, str]): En-têtes à envoyer. Obligatoire.
            **kwargs: Arguments transmis à `httpx.request` (params, json,
                files, data).

        Returns:
            httpx.Response: La réponse HTTP brute (le mapping en exception métier
            est réalisé par `_map_response`).

        Raises:
            APIUnavailableError: Après épuisement des tentatives sur une erreur
                transitoire (timeout, réseau, ou 502/503/504 idempotent).
        """
        url = f"{self.base_url}{endpoint}"
        attempt = 0
        while True:
            try:
                response = httpx.request(
                    method, url, headers=headers, timeout=self._timeout, **kwargs
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                # Timeouts et erreurs de connexion/lecture : transitoires.
                if idempotent and attempt < self._max_retries:
                    self._log_retry(method, url, attempt, exc.__class__.__name__)
                    self._sleep_backoff(attempt)
                    attempt += 1
                    continue
                logger.error(
                    "API injoignable après %d tentative(s) : %s %s (%s)",
                    attempt + 1,
                    method,
                    url,
                    exc.__class__.__name__,
                )
                raise APIUnavailableError() from exc

            # Statuts serveur transitoires : mêmes règles de rejeu.
            if response.status_code in _RETRYABLE_STATUS:
                if idempotent and attempt < self._max_retries:
                    self._log_retry(
                        method, url, attempt, f"HTTP {response.status_code}"
                    )
                    self._sleep_backoff(attempt)
                    attempt += 1
                    continue
                if idempotent:
                    logger.error(
                        "API injoignable après %d tentative(s) : %s %s (HTTP %d)",
                        attempt + 1,
                        method,
                        url,
                        response.status_code,
                    )
                    raise APIUnavailableError(status_code=response.status_code)
                # Non idempotent : pas de rejeu ; `_map_response` lèvera ServerError.

            return response

    def _sleep_backoff(self, attempt: int) -> None:
        """Attend selon un backoff exponentiel avant un nouveau rejeu.

        Args:
            attempt (int): Numéro de tentative déjà effectuée (0 pour le premier
                rejeu). Le délai vaut `backoff * 2 ** attempt`. Obligatoire.
        """
        time.sleep(self._retry_backoff * (2**attempt))

    def _log_retry(self, method: str, url: str, attempt: int, reason: str) -> None:
        """Journalise (niveau warning) une tentative de rejeu à venir.

        Args:
            method (str): Méthode HTTP. Obligatoire.
            url (str): URL cible. Obligatoire.
            attempt (int): Numéro de la tentative déjà échouée (0-indexé).
                Obligatoire.
            reason (str): Cause du rejeu (exception ou statut HTTP). Obligatoire.
        """
        logger.warning(
            "Rejeu %d/%d : %s %s (cause : %s)",
            attempt + 1,
            self._max_retries,
            method,
            url,
            reason,
        )

    def _map_response(self, response: httpx.Response) -> Any:
        """Traduit une réponse HTTP en résultat métier ou en exception dédiée.

        Aucune exception `httpx` ni code brut ne fuit vers les appelants : les
        statuts d'erreur sont convertis en exceptions de `clients.exceptions`.

        Args:
            response (httpx.Response): Réponse HTTP à interpréter. Obligatoire.

        Returns:
            Le corps JSON décodé (dict ou list) pour une réponse à contenu, ou
            `True` pour un 204 (succès sans contenu, ex. suppression).

        Raises:
            TokenExpiredError: Réponse 401 (la session Django est d'abord vidée).
            ResourceNotFoundError: Réponse 404.
            ResourceConflictError: Réponse 409 (message de conflit conservé).
            APIValidationError: Réponse 422 (détail de validation conservé).
            ServerError: Réponse 5xx (non transitoire).
            APIClientError: Tout autre statut 4xx non spécifique (400, 403, ...).
        """
        status = response.status_code

        # --- Succès ---
        if status < 400:
            # cas suppression (204 = succès pas de contenu JSON)
            if status == 204:
                return True
            return response.json()

        # --- Erreurs : traduction en exceptions métier ---
        if status == 401:
            # destruction de la session Django + message pour l'utilisateur
            self.request.session.flush()
            messages.error(
                self.request, "Votre session a expiré. Veuillez vous reconnecter."
            )
            raise TokenExpiredError()
        if status == 404:
            raise ResourceNotFoundError()
        if status == 409:
            raise ResourceConflictError(detail=self._extract_detail(response))
        if status == 422:
            raise APIValidationError(detail=self._extract_detail(response))
        if status >= 500:
            raise ServerError(status_code=status)

        # Autres 4xx (400, 403, ...) : erreur générique de la couche cliente.
        raise APIClientError(f"Erreur API (HTTP {status}).", status_code=status)

    @staticmethod
    def _extract_detail(response: httpx.Response) -> Any:
        """Extrait le champ `detail` d'un corps d'erreur JSON, si présent.

        Args:
            response (httpx.Response): Réponse (typiquement 422). Obligatoire.

        Returns:
            Le contenu de `detail` (liste d'erreurs `HTTPValidationError`) si le
            corps est un objet JSON, le corps entier s'il est d'une autre forme,
            ou `None` si le corps n'est pas du JSON.
        """
        try:
            corps = response.json()
        except ValueError:
            return None
        if isinstance(corps, dict):
            return corps.get("detail")
        return corps

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Émet une requête GET authentifiée vers l'API (idempotente, rejouable).

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`
                (ex. `/clients/`). Obligatoire.
            params (dict | None): Paramètres de requête (query string).
                Optionnel, `None` par défaut.

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse.

        Raises:
            TokenExpiredError: Authentification expirée (401).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable après retries
                (`APIUnavailableError`).
        """
        response = self._request(
            "GET", endpoint, idempotent=True, headers=self.headers, params=params
        )
        return self._map_response(response)

    def post(self, endpoint: str, data: dict[str, Any] | None = None) -> Any:
        """Émet une requête POST authentifiée avec un corps JSON.

        POST = création non idempotente : elle n'est JAMAIS rejouée.

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.
            data (dict | None): Corps JSON à envoyer. Optionnel, `None` par
                défaut (aucun corps).

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse, ou `True` sur 204.

        Raises:
            TokenExpiredError: Authentification expirée (401).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (`APIUnavailableError`).
        """
        response = self._request(
            "POST", endpoint, idempotent=False, headers=self.headers, json=data
        )
        return self._map_response(response)

    def put(self, endpoint: str, data: dict[str, Any] | None = None) -> Any:
        """Émet une requête PUT authentifiée avec un corps JSON (idempotente).

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.
            data (dict | None): Corps JSON à envoyer. Optionnel, `None` par
                défaut.

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse, ou `True` sur 204.

        Raises:
            TokenExpiredError: Authentification expirée (401).
            APIClientError: Toute autre erreur API mappée ou API injoignable
                (`APIUnavailableError`).
        """
        response = self._request(
            "PUT", endpoint, idempotent=True, headers=self.headers, json=data
        )
        return self._map_response(response)

    def delete(self, endpoint: str) -> Any:
        """Émet une requête DELETE authentifiée (idempotente, rejouable).

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.

        Returns:
            `True` sur 204 (cas usuel de suppression), sinon le corps JSON
            décodé si l'API renvoie un contenu.

        Raises:
            TokenExpiredError: Authentification expirée (401).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                5xx serveur) ou API injoignable (`APIUnavailableError`).
        """
        response = self._request(
            "DELETE", endpoint, idempotent=True, headers=self.headers
        )
        return self._map_response(response)

    def patch(self, endpoint: str, data: dict[str, Any] | None = None) -> Any:
        """Émet une requête PATCH authentifiée avec un corps JSON.

        PATCH n'est pas garanti idempotent (contrat OpenAPI) : par prudence, il
        n'est JAMAIS rejoué, comme POST.

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.
            data (dict | None): Corps JSON partiel à envoyer. Optionnel, `None`
                par défaut.

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse, ou `True` sur 204.

        Raises:
            TokenExpiredError: Authentification expirée (401).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (`APIUnavailableError`).
        """
        response = self._request(
            "PATCH", endpoint, idempotent=False, headers=self.headers, json=data
        )
        return self._map_response(response)

    def post_file(
        self,
        endpoint: str,
        files: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> Any:
        """POST multipart/form-data (upload de fichiers vers l'API).

        On n'envoie PAS de Content-Type explicite : httpx calcule lui-même
        le boundary multipart à partir de `files`. Comme tout POST, l'upload
        n'est jamais rejoué (non idempotent).

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.
            files (dict): Fichiers au format attendu par httpx, p. ex.
                `{"file": (nom, flux, content_type)}`. Obligatoire.
            data (dict | None): Champs de formulaire additionnels. Optionnel,
                `None` par défaut.

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse (ex. 202 accepté),
            ou `True` sur 204.

        Raises:
            TokenExpiredError: Authentification expirée (401).
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (`APIUnavailableError`).
        """
        response = self._request(
            "POST",
            endpoint,
            idempotent=False,
            headers=self.auth_headers,
            files=files,
            data=data,
        )
        return self._map_response(response)
