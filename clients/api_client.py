"""Client d'authentification autonome contre l'API FastAPI (`API_DATA_URL`).

Contrairement aux clients métier, `APIAuthClient` n'hérite pas de
`BaseAPIClient` : il gère l'étape d'authentification *avant* l'obtention du JWT,
donc sans en-tête `Authorization` ni session à disposition. Il ne couvre qu'une
seule route du contrat :

- POST /auth/token : échange identifiants (flux OAuth2 password, corps
  form-urlencoded) contre un JWT.
"""

import httpx
from django.conf import settings


class APIAuthClient:
    """Client dédié à la connexion (obtention du JWT) sur l'API.

    N'utilise ni JWT ni session (l'utilisateur n'est pas encore authentifié) ;
    il émet donc directement une requête `httpx` non authentifiée, à la
    différence des clients métier qui passent par `BaseAPIClient`.

    Attributes:
        base_url (str): URL de base de l'API, issue de `settings.API_DATA_URL`.
    """

    def __init__(self):
        """Initialise le client avec l'URL de base de l'API."""
        self.base_url = settings.API_DATA_URL

    def login(self, email, password):
        """Envoie les identifiants à l'API et récupère le JWT.

        Appelle POST /auth/token (flux OAuth2 password, corps
        `application/x-www-form-urlencoded`). L'email est transmis dans le champ
        `username` attendu par le contrat.

        Args:
            email (str): Adresse email de l'utilisateur, envoyée comme
                `username`. Obligatoire.
            password (str): Mot de passe en clair. Obligatoire.

        Returns:
            dict: En cas de succès, le corps JSON de l'API (contenant le JWT,
            p. ex. `access_token` et `token_type`). En cas d'échec, un
            dictionnaire `{"error": <message>}` :
            identifiants invalides (401), autre erreur HTTP, ou serveur
            injoignable.

        Raises:
            Aucune : les erreurs HTTP et réseau sont capturées et converties en
            dictionnaire `{"error": ...}`.
        """
        url = f"{self.base_url}/auth/token"

        try:
            payload = {"username": email, "password": password}

            response = httpx.post(url, data=payload)
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Email ou mot de passe incorrect"}
            return {"error": f"Erreur API ({e.response.status_code})"}
        except httpx.RequestError:
            return {"error": "Impossible de contacter le serveur d'authentification"}
