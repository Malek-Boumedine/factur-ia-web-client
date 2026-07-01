"""Client HTTP pour le catalogue de produits.

Couvre le domaine `catalogue-produits` de l'API :

- GET /catalogue-produits/ : liste paginée du catalogue (skip/limit).
- POST /catalogue-produits/ : création d'un produit (schéma CatalogueCreate).
- GET /catalogue-produits/{produit_id} : détail d'un produit.
- PATCH /catalogue-produits/{produit_id} : mise à jour partielle
  (schéma CatalogueUpdate).
- DELETE /catalogue-produits/{produit_id} : suppression/désactivation.
"""

from typing import Any

from .base_client import BaseAPIClient


class ProduitsClient(BaseAPIClient):
    """Client HTTP pour le catalogue de produits (`/catalogue-produits`).

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    Chaque méthode correspond exactement à une route du contrat OpenAPI.
    """

    def list_products(self, skip: int | None = None, limit: int | None = None) -> Any:
        """Liste paginée du catalogue de produits.

        Appelle GET /catalogue-produits/. Les paramètres `skip` et `limit` ne
        sont transmis en query string que s'ils sont fournis.

        Args:
            skip (int | None): Nombre d'éléments à ignorer (pagination).
                Optionnel, `None` par défaut.
            limit (int | None): Nombre maximum d'éléments à renvoyer.
                Optionnel, `None` par défaut.

        Returns:
            list: Liste des produits (dictionnaires) renvoyée par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        params: dict[str, int] = {}
        if skip is not None:
            params["skip"] = skip
        if limit is not None:
            params["limit"] = limit
        return self.get("/catalogue-produits/", params=params or None)

    def get_product(self, produit_id: int) -> Any:
        """Récupère le détail d'un produit.

        Appelle GET /catalogue-produits/{produit_id}.

        Args:
            produit_id (int): Identifiant du produit. Obligatoire.

        Returns:
            dict: Le produit demandé, tel que renvoyé par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        return self.get(f"/catalogue-produits/{produit_id}")

    def create_product(self, payload: dict[str, Any]) -> Any:
        """Crée un produit au catalogue.

        Appelle POST /catalogue-produits/ (schéma CatalogueCreate). Champs
        obligatoires du schéma : `designation`, `prix_unitaire_ht`,
        `id_taux_tva`.

        Args:
            payload (dict[str, Any]): Données du produit, conformes au schéma
                CatalogueCreate. Obligatoire.

        Returns:
            dict: Le produit créé, tel que renvoyé par l'API (201).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422
                validation).
        """
        return self.post("/catalogue-produits/", data=payload)

    def update_product(self, produit_id: int, payload: dict[str, Any]) -> Any:
        """Met à jour partiellement un produit.

        Appelle PATCH /catalogue-produits/{produit_id} (schéma CatalogueUpdate,
        tous les champs optionnels).

        Args:
            produit_id (int): Identifiant du produit à modifier. Obligatoire.
            payload (dict[str, Any]): Champs partiels à mettre à jour, conformes
                au schéma CatalogueUpdate. Obligatoire.

        Returns:
            dict: Le produit mis à jour, tel que renvoyé par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422
                validation).
        """
        return self.patch(f"/catalogue-produits/{produit_id}", data=payload)

    def delete_product(self, produit_id: int) -> Any:
        """Supprime (désactive) un produit.

        Appelle DELETE /catalogue-produits/{produit_id}.
        # Note : le contrat déclare une réponse 200 pour cette suppression
        # (et non 204), donc l'API renvoie ici un corps JSON, pas `True`.

        Args:
            produit_id (int): Identifiant du produit à supprimer. Obligatoire.

        Returns:
            dict: Le corps JSON renvoyé par l'API (réponse 200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        return self.delete(f"/catalogue-produits/{produit_id}")
