import httpx
from django.conf import settings
from django.contrib import messages


class TokenExpiredError(Exception):
    """Exception personnalisée levée lorsque l'API refuse le token."""

    pass


class BaseAPIClient:
    """
    Client parent pour toutes les requêtes vers l'API FastAPI.
    Injecte le JWT et gère la déconnexion forcée en cas d'expiration.
    """

    def __init__(self, request):
        self.request = request
        self.base_url = settings.API_DATA_URL

    @property
    def auth_headers(self):
        """En-têtes d'authentification (sans Content-Type, pour le multipart)."""
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
        """Construit les en-têtes JSON avec le token et l'ID de l'entreprise."""
        return {**self.auth_headers, "Content-Type": "application/json"}

    def _handle_response(self, response):
        """Centralise la vérification des erreurs et de l'expiration du token."""
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
        url = f"{self.base_url}{endpoint}"
        response = httpx.get(url, headers=self.headers, params=params)
        return self._handle_response(response)

    def post(self, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"
        response = httpx.post(url, headers=self.headers, json=data)
        return self._handle_response(response)

    def put(self, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"
        response = httpx.put(url, headers=self.headers, json=data)
        return self._handle_response(response)

    def delete(self, endpoint):
        url = f"{self.base_url}{endpoint}"
        response = httpx.delete(url, headers=self.headers)
        return self._handle_response(response)

    def patch(self, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"
        response = httpx.patch(url, headers=self.headers, json=data)
        return self._handle_response(response)

    def post_file(self, endpoint, files, data=None):
        """POST multipart/form-data (upload de fichiers vers l'API).

        On n'envoie PAS de Content-Type explicite : httpx calcule lui-même
        le boundary multipart à partir de `files`.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.post(url, headers=self.auth_headers, files=files, data=data)
        return self._handle_response(response)
