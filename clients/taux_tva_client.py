"""Client HTTP pour les taux de TVA (données de référence).

Couvre le domaine `taux-tva` de l'API :

- GET /taux-tva/ : liste des taux de TVA (filtrable par statut actif).
- GET /taux-tva/{id} : détail d'un taux.
- POST /taux-tva/ : création (schéma TauxTvaCreate).
- PATCH /taux-tva/{id} : mise à jour partielle (schéma TauxTvaUpdate).
- DELETE /taux-tva/{id} : désactivation (soft delete, `est_actif=False`).

Les écritures (POST/PATCH/DELETE) sont réservées côté API aux administrateurs
plateforme. La lecture alimente aussi les listes déroulantes des formulaires
(catalogue produits).
"""

from typing import Any

from .base_client import BaseAPIClient


class TauxTvaClient(BaseAPIClient):
    """Client HTTP pour les taux de TVA (`/taux-tva/`).

    Hérite de `BaseAPIClient` ; le JWT est injecté depuis la session. La route
    est globale (pas de tenant), le header `x-entreprise-id` éventuellement
    transmis reste sans effet.
    """

    def list_taux(self, est_actif: bool | None = None) -> Any:
        """Liste les taux de TVA de référence.

        Appelle GET /taux-tva/. Le filtre `est_actif` n'est transmis que s'il
        est fourni (`est_actif=True` pour ne proposer que les taux actifs dans
        les formulaires de saisie).

        Args:
            est_actif (bool | None): Filtre sur le statut actif/inactif.
                `None` = tous les taux. Optionnel.

        Returns:
            list: Liste des taux (schéma TauxTvaRead : `id`, `libelle`,
            `taux` en chaîne, `code_comptable`, `est_actif`).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        params: dict[str, Any] = {}
        if est_actif is not None:
            params["est_actif"] = est_actif
        return self.get("/taux-tva/", params=params or None)

    def get_taux(self, taux_tva_id: int) -> Any:
        """Récupère le détail d'un taux de TVA.

        Appelle GET /taux-tva/{taux_tva_id}.

        Args:
            taux_tva_id (int): Identifiant du taux à récupérer. Obligatoire.

        Returns:
            dict: Le taux (schéma TauxTvaRead).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Taux introuvable (404).
            APIClientError: Toute autre erreur API mappée ou API injoignable
                (APIUnavailableError).
        """
        return self.get(f"/taux-tva/{taux_tva_id}")

    def create_taux(self, payload: dict[str, Any]) -> Any:
        """Crée un taux de TVA (admin plateforme).

        Appelle POST /taux-tva/ (schéma TauxTvaCreate). Champs obligatoires :
        `taux` et `libelle`.

        Args:
            payload (dict[str, Any]): Données du taux, conformes au schéma
                TauxTvaCreate. Obligatoire.

        Returns:
            dict: Le taux créé, tel que renvoyé par l'API (201).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceConflictError: Taux déjà existant (409, valeur unique).
            APIClientError: Toute autre erreur API mappée (403 non admin,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.post("/taux-tva/", data=payload)

    def update_taux(self, taux_tva_id: int, payload: dict[str, Any]) -> Any:
        """Met à jour partiellement un taux de TVA (admin plateforme).

        Appelle PATCH /taux-tva/{taux_tva_id} (schéma TauxTvaUpdate, tous les
        champs optionnels). Sert aussi à la réactivation (`est_actif=True`).

        Args:
            taux_tva_id (int): Identifiant du taux à modifier. Obligatoire.
            payload (dict[str, Any]): Champs partiels à mettre à jour, conformes
                au schéma TauxTvaUpdate. Obligatoire.

        Returns:
            dict: Le taux mis à jour, tel que renvoyé par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Taux introuvable (404).
            ResourceConflictError: Taux déjà existant (409, valeur unique).
            APIClientError: Toute autre erreur API mappée (403 non admin,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.patch(f"/taux-tva/{taux_tva_id}", data=payload)

    def deactivate_taux(self, taux_tva_id: int) -> Any:
        """Désactive un taux de TVA (soft delete, admin plateforme).

        Appelle DELETE /taux-tva/{taux_tva_id} : l'API bascule `est_actif` à
        `False` (le taux n'est plus proposé aux nouvelles saisies). La
        réactivation se fait via `update_taux(id, {"est_actif": True})`.

        Args:
            taux_tva_id (int): Identifiant du taux à désactiver. Obligatoire.

        Returns:
            bool: `True` en cas de succès (réponse 204 sans contenu).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Taux introuvable (404).
            APIClientError: Toute autre erreur API mappée (403 non admin,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.delete(f"/taux-tva/{taux_tva_id}")
