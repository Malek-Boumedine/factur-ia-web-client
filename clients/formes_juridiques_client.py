"""Client HTTP pour les formes juridiques (données de référence).

Couvre le domaine `formes-juridiques` de l'API :

- GET /formes-juridiques/ : liste des formes juridiques (filtrable par statut
  actif).

La lecture alimente les listes déroulantes des formulaires (identité légale
d'une entreprise).
"""

from typing import Any

from .base_client import BaseAPIClient


class FormesJuridiquesClient(BaseAPIClient):
    """Client HTTP pour les formes juridiques (`/formes-juridiques/`).

    Hérite de `BaseAPIClient` ; le JWT est injecté depuis la session. La route
    est globale (pas de tenant), le header `x-entreprise-id` éventuellement
    transmis reste sans effet.
    """

    def list_formes(self, est_actif: bool | None = None) -> Any:
        """Liste les formes juridiques de référence.

        Appelle GET /formes-juridiques/. Le filtre `est_actif` n'est transmis
        que s'il est fourni (`est_actif=True` pour ne proposer que les formes
        actives dans les formulaires de saisie).

        Args:
            est_actif (bool | None): Filtre sur le statut actif/inactif.
                `None` = toutes les formes. Optionnel.

        Returns:
            list: Liste des formes (schéma FormeJuridiqueRead : `id`, `code`,
            `libelle`, `est_actif`), triée par libellé côté API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        params: dict[str, Any] = {}
        if est_actif is not None:
            params["est_actif"] = est_actif
        return self.get("/formes-juridiques/", params=params or None)
