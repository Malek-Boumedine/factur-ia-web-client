"""Client HTTP pour les taux de TVA (données de référence).

Couvre la partie lecture du domaine `taux-tva` de l'API :

- GET /taux-tva/ : liste des taux de TVA (filtrable par statut actif).

Les routes d'administration des taux (POST/PATCH/DELETE, réservées à l'admin
plateforme) ne sont pas couvertes ici : le front n'en a besoin que pour
alimenter les listes déroulantes des formulaires (catalogue produits).
"""

from typing import Any

from .base_client import BaseAPIClient


class TauxTvaClient(BaseAPIClient):
    """Client HTTP pour la lecture des taux de TVA (`/taux-tva/`).

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
