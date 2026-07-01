"""Client HTTP pour la gestion des clients (tiers facturés).

Couvre le domaine `clients` de l'API :

- GET /clients/ : liste des clients de l'entreprise active.
- POST /clients/ : création d'un client (schéma ClientCreate).
- GET /clients/{client_id} : détail d'un client.
- PATCH /clients/{client_id} : mise à jour partielle (schéma ClientUpdate).
- DELETE /clients/{client_id} : suppression/désactivation d'un client.
- GET /clients/recherche-sirene/{identifiant} : recherche d'entreprise via
  l'annuaire SIRENE (n'exige pas le tenant `x-entreprise-id`).
"""

from typing import Any

from .base_client import BaseAPIClient


class ClientsClient(BaseAPIClient):
    """Client HTTP pour la gestion des clients (tiers facturés).

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    Chaque méthode correspond exactement à une route du contrat OpenAPI.
    """

    def list_clients(self) -> Any:
        """Liste les clients de l'entreprise active.

        Appelle GET /clients/.

        Returns:
            list: Liste des clients (dictionnaires) renvoyée par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        return self.get("/clients/")

    def get_client(self, client_id: int) -> Any:
        """Récupère le détail d'un client.

        Appelle GET /clients/{client_id}.

        Args:
            client_id (int): Identifiant du client. Obligatoire.

        Returns:
            dict: Le client demandé, tel que renvoyé par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        return self.get(f"/clients/{client_id}")

    def create_client(self, payload: dict[str, Any]) -> Any:
        """Crée un client.

        Appelle POST /clients/ (schéma ClientCreate). Champs obligatoires du
        schéma : `raison_sociale`, `code_postal`, `ville`.

        Args:
            payload (dict[str, Any]): Données du client, conformes au schéma
                ClientCreate. Obligatoire.

        Returns:
            dict: Le client créé, tel que renvoyé par l'API (201).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422
                validation).
        """
        return self.post("/clients/", data=payload)

    def update_client(self, client_id: int, payload: dict[str, Any]) -> Any:
        """Met à jour partiellement un client.

        Appelle PATCH /clients/{client_id} (schéma ClientUpdate, tous les champs
        optionnels).

        Args:
            client_id (int): Identifiant du client à modifier. Obligatoire.
            payload (dict[str, Any]): Champs partiels à mettre à jour, conformes
                au schéma ClientUpdate. Obligatoire.

        Returns:
            dict: Le client mis à jour, tel que renvoyé par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422
                validation).
        """
        return self.patch(f"/clients/{client_id}", data=payload)

    def delete_client(self, client_id: int) -> Any:
        """Supprime (désactive) un client.

        Appelle DELETE /clients/{client_id}.

        Args:
            client_id (int): Identifiant du client à supprimer. Obligatoire.

        Returns:
            bool: `True` en cas de succès (réponse 204 sans contenu).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        return self.delete(f"/clients/{client_id}")

    def search_sirene(self, identifiant: str) -> Any:
        """Recherche une entreprise dans l'annuaire SIRENE.

        Appelle GET /clients/recherche-sirene/{identifiant}. Cette route n'exige
        pas le header `x-entreprise-id`.

        Args:
            identifiant (str): Numéro SIREN (9 chiffres) ou SIRET (14 chiffres).
                Obligatoire.

        Returns:
            dict: Les informations d'entreprise renvoyées par l'API SIRENE.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422).
        """
        return self.get(f"/clients/recherche-sirene/{identifiant}")
