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

    def list_clients(
        self,
        search: str | None = None,
        est_actif: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Any:
        """Liste paginée des clients de l'entreprise active.

        Appelle GET /clients/. Depuis la mise à jour du contrat, l'API renvoie
        une enveloppe paginée `Page[ClientRead]` de la forme
        ``{"items": [...], "total": N, "skip": ..., "limit": ...}`` (et non plus
        une liste directe). Les paramètres optionnels ne sont transmis en query
        string que lorsqu'ils sont fournis.

        Args:
            search (str | None): Terme de recherche sur la raison sociale, le
                SIRET ou l'email. Optionnel.
            est_actif (bool | None): Filtre sur le statut actif/inactif.
                `None` = pas de filtre (tous les clients). Optionnel.
            skip (int): Décalage de pagination (offset). Défaut 0.
            limit (int): Nombre maximum d'éléments à renvoyer (max 100 côté
                API). Défaut 100.

        Returns:
            dict: L'enveloppe paginée `Page[ClientRead]` renvoyée par l'API,
            avec les clés `items` (liste) et `total` (nombre total, tous
            filtres appliqués).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if search:
            params["search"] = search
        if est_actif is not None:
            params["est_actif"] = est_actif
        return self.get("/clients/", params=params)

    def get_client(self, client_id: int) -> Any:
        """Récupère le détail d'un client.

        Appelle GET /clients/{client_id}.

        Args:
            client_id (int): Identifiant du client. Obligatoire.

        Returns:
            dict: Le client demandé, tel que renvoyé par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
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
            ResourceConflictError: En cas de réponse 409 (SIRET ou numéro de
                TVA déjà utilisé par un autre client).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
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
            ResourceConflictError: En cas de réponse 409 (SIRET ou numéro de
                TVA déjà utilisé par un autre client).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
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
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
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
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.get(f"/clients/recherche-sirene/{identifiant}")
