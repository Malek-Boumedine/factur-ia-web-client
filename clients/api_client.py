"""Client d'authentification autonome contre l'API FastAPI (`API_DATA_URL`).

Contrairement aux clients métier, `APIAuthClient` n'hérite pas de
`BaseAPIClient` : il gère l'étape d'authentification *avant* l'obtention du JWT,
donc sans en-tête `Authorization` ni session à disposition. Il ne couvre qu'une
seule route du contrat :

- POST /auth/token : échange identifiants (flux OAuth2 password, corps
  form-urlencoded) contre un JWT.

En production, l'ingress de l'API data exige en revanche le jeton d'identité
Google (IAM Cloud Run) sur TOUS les appels, y compris celui-ci : il part dans
`X-Serverless-Authorization`, comme dans `BaseAPIClient` (voir
`clients.gcp_identity`), même si `Authorization` est libre sur ce chemin —
une seule convention pour toute la couche cliente.
"""

from typing import Any

import httpx
from django.conf import settings

from . import gcp_identity
from .exceptions import APIUnavailableError

# Message unique pour toute impossibilité de joindre l'API : erreur réseau,
# ou jeton d'identité IAM inobtenable (l'API est de fait injoignable).
_MSG_INJOIGNABLE = "Impossible de contacter le serveur d'authentification"


class APIAuthClient:
    """Client dédié à la connexion (obtention du JWT) sur l'API.

    N'utilise ni JWT ni session (l'utilisateur n'est pas encore authentifié) ;
    il émet donc directement une requête `httpx` sans `Authorization`, à la
    différence des clients métier qui passent par `BaseAPIClient`. Le jeton
    d'identité IAM Cloud Run (`X-Serverless-Authorization`) est en revanche
    envoyé comme partout ailleurs lorsque `API_IAM_AUTH_ENABLED` est vrai.

    Attributes:
        base_url (str): URL de base de l'API, issue de `settings.API_DATA_URL`.
    """

    def __init__(self) -> None:
        """Initialise le client avec l'URL de base de l'API."""
        self.base_url = settings.API_DATA_URL

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Envoie les identifiants à l'API et récupère le JWT.

        Appelle POST /auth/token (flux OAuth2 password, corps
        `application/x-www-form-urlencoded`). L'email est transmis dans le champ
        `username` attendu par le contrat. Si l'authentification IAM est
        activée, le jeton d'identité Google part dans
        `X-Serverless-Authorization`.

        Args:
            email (str): Adresse email de l'utilisateur, envoyée comme
                `username`. Obligatoire.
            password (str): Mot de passe en clair. Obligatoire.

        Returns:
            dict: En cas de succès, le corps JSON de l'API (contenant le JWT,
            p. ex. `access_token` et `token_type`). En cas d'échec, un
            dictionnaire `{"error": <message>}` :
            identifiants invalides (401), autre erreur HTTP, serveur
            injoignable, ou jeton d'identité IAM inobtenable.

        Raises:
            Aucune : les erreurs HTTP, réseau et d'obtention du jeton IAM sont
            capturées et converties en dictionnaire `{"error": ...}`.
        """
        url = f"{self.base_url}/auth/token"

        # Contrat de la vue de connexion : jamais d'exception, toujours un
        # dictionnaire. L'échec d'obtention du jeton IAM est donc converti ici.
        try:
            headers = {
                "Accept": "application/json",
                **gcp_identity.serverless_authorization_header(),
            }
        except APIUnavailableError:
            return {"error": _MSG_INJOIGNABLE}

        try:
            payload = {"username": email, "password": password}

            response = httpx.post(url, data=payload, headers=headers)
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Email ou mot de passe incorrect"}
            return {"error": f"Erreur API ({e.response.status_code})"}
        except httpx.RequestError:
            return {"error": _MSG_INJOIGNABLE}
