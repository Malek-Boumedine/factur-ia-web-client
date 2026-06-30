import httpx
from django.conf import settings


class APIAuthClient:
    def __init__(self):
        self.base_url = settings.API_DATA_URL

    def login(self, email, password):
        """Envoie les identifiants à l'API et récupère le JWT."""
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
