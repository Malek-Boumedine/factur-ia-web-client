"""Socle commun des clients HTTP vers l'API FastAPI (`API_DATA_URL`).

Ce module fournit :

- `TokenExpiredError` : exception levée lorsqu'un appel renvoie 401.
- `BaseAPIClient` : classe parente dont héritent tous les clients métier
  (`ClientsClient`, `ProduitsClient`, `FacturesClient`, `AbonnementsClient`,
  `DocumentsClient`, `UtilisateursClient`). Elle centralise la construction des
  en-têtes (JWT + tenant `x-entreprise-id`), l'émission des requêtes `httpx`
  (GET/POST/PUT/PATCH/DELETE + upload multipart) et la gestion des erreurs.

Ce fichier ne cible aucune route métier précise : il expose les primitives HTTP
réutilisées par les sous-classes, qui portent, elles, les chemins du contrat.
"""

import httpx
from django.conf import settings
from django.contrib import messages


class TokenExpiredError(Exception):
    """Exception personnalisée levée lorsque l'API refuse le token.

    Levée par `BaseAPIClient._handle_response` sur une réponse 401, après avoir
    vidé la session Django. Permet aux vues de stopper le rendu et de rediriger
    l'utilisateur vers la page de connexion.
    """

    pass


class BaseAPIClient:
    """Client parent pour toutes les requêtes vers l'API FastAPI.

    Injecte le JWT et gère la déconnexion forcée en cas d'expiration.

    Toutes les sous-classes héritent de cette classe et réutilisent ses méthodes
    HTTP (`get`, `post`, `put`, `patch`, `delete`, `post_file`) ; elles ne
    doivent jamais appeler `httpx` directement. L'authentification (Bearer JWT)
    et le contexte multi-tenant (`x-entreprise-id`) sont résolus depuis la
    session Django et injectés automatiquement dans les en-têtes.

    Attributes:
        request: La requête Django courante (`HttpRequest`), source de la
            session contenant le JWT et l'identifiant d'entreprise.
        base_url (str): URL de base de l'API, issue de `settings.API_DATA_URL`.
    """

    def __init__(self, request):
        """Initialise le client à partir de la requête Django courante.

        Args:
            request: Requête Django (`HttpRequest`) en cours. Sa session
                fournit `jwt_token` et `entreprise_id` utilisés pour l'auth
                et le contexte tenant. Obligatoire.
        """
        self.request = request
        self.base_url = settings.API_DATA_URL

    @property
    def auth_headers(self):
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
    def headers(self):
        """Construit les en-têtes JSON avec le token et l'ID de l'entreprise.

        Reprend `auth_headers` et y ajoute `Content-Type: application/json`.
        Utilisé pour toutes les requêtes à corps JSON (GET/POST/PUT/PATCH/DELETE).

        Returns:
            dict[str, str]: En-têtes de `auth_headers` enrichis du
            `Content-Type` JSON.
        """
        return {**self.auth_headers, "Content-Type": "application/json"}

    def _handle_response(self, response):
        """Centralise la vérification des erreurs et de l'expiration du token.

        Args:
            response (httpx.Response): Réponse HTTP renvoyée par httpx.
                Obligatoire.

        Returns:
            Le corps JSON décodé (dict ou list) pour une réponse à contenu, ou
            `True` pour un 204 (succès sans contenu, ex. suppression).

        Raises:
            TokenExpiredError: Si la réponse est un 401. La session Django est
                d'abord vidée et un message d'erreur est ajouté.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (400, 403,
                422, 500, ...), laissée remonter telle quelle.
        """
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # si token invalide/expiré
            if e.response.status_code == 401:
                # destruction de la session Django
                self.request.session.flush()
                # message d'alerte pour l'utilisateur
                messages.error(
                    self.request, "Votre session a expiré. Veuillez vous reconnecter."
                )
                # lever l'erreur pour stopper le chargement de la page
                raise TokenExpiredError("Token expiré ou invalide.")

            # Si c'est une autre erreur (400, 403, 500), on la laisse remonter normalement
            raise e

        # cas suppression (204 = succès pas de contenu JSON)
        if response.status_code == 204:
            return True

        return response.json()

    def get(self, endpoint, params=None):
        """Émet une requête GET authentifiée vers l'API.

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`
                (ex. `/clients/`). Obligatoire.
            params (dict | None): Paramètres de requête (query string).
                Optionnel, `None` par défaut.

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.get(url, headers=self.headers, params=params)
        return self._handle_response(response)

    def post(self, endpoint, data=None):
        """Émet une requête POST authentifiée avec un corps JSON.

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.
            data (dict | None): Corps JSON à envoyer. Optionnel, `None` par
                défaut (aucun corps).

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse, ou `True` sur 204.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.post(url, headers=self.headers, json=data)
        return self._handle_response(response)

    def put(self, endpoint, data=None):
        """Émet une requête PUT authentifiée avec un corps JSON.

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.
            data (dict | None): Corps JSON à envoyer. Optionnel, `None` par
                défaut.

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse, ou `True` sur 204.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.put(url, headers=self.headers, json=data)
        return self._handle_response(response)

    def delete(self, endpoint):
        """Émet une requête DELETE authentifiée.

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.

        Returns:
            `True` sur 204 (cas usuel de suppression), sinon le corps JSON
            décodé si l'API renvoie un contenu.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.delete(url, headers=self.headers)
        return self._handle_response(response)

    def patch(self, endpoint, data=None):
        """Émet une requête PATCH authentifiée avec un corps JSON.

        Args:
            endpoint (str): Chemin de la route, concaténé à `base_url`.
                Obligatoire.
            data (dict | None): Corps JSON partiel à envoyer. Optionnel, `None`
                par défaut.

        Returns:
            Le corps JSON décodé (dict ou list) de la réponse, ou `True` sur 204.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.patch(url, headers=self.headers, json=data)
        return self._handle_response(response)

    def post_file(self, endpoint, files, data=None):
        """POST multipart/form-data (upload de fichiers vers l'API).

        On n'envoie PAS de Content-Type explicite : httpx calcule lui-même
        le boundary multipart à partir de `files`.

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
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.post(url, headers=self.auth_headers, files=files, data=data)
        return self._handle_response(response)
