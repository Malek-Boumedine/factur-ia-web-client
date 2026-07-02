"""Client HTTP pour la gestion des administrateurs de plateforme.

Couvre le domaine `admins-plateforme` de l'API :

- GET /admins-plateforme/ : liste des administrateurs de plateforme.
- GET /admins-plateforme/recherche-utilisateur : recherche d'utilisateurs par
  fragment d'email (pour désigner qui promouvoir).
- POST /admins-plateforme/{utilisateur_id}/promouvoir : promotion.
- POST /admins-plateforme/{utilisateur_id}/revoquer : révocation.

Ces routes sont **globales** : l'administrateur de plateforme agit hors de tout
tenant. Ce client retire donc volontairement le header `x-entreprise-id`
injecté par défaut par `BaseAPIClient`.
"""

from typing import Any

from .base_client import BaseAPIClient


class AdminsPlateformeClient(BaseAPIClient):
    """Client HTTP pour la gestion des administrateurs de plateforme.

    Hérite de `BaseAPIClient` (JWT injecté depuis la session) mais surcharge
    `auth_headers` pour **ne pas** transmettre `x-entreprise-id` : ces routes
    sont globales et ne portent pas de tenant. Chaque méthode correspond
    exactement à une route du contrat OpenAPI.
    """

    @property
    def auth_headers(self) -> dict[str, str]:
        """En-têtes d'authentification sans le tenant `x-entreprise-id`.

        Reprend les en-têtes de `BaseAPIClient` (dont `Authorization: Bearer`)
        et retire l'éventuel `x-entreprise-id`, car l'administrateur de
        plateforme agit globalement.

        Returns:
            dict[str, str]: En-têtes d'authentification sans le header de tenant.
        """
        return {k: v for k, v in super().auth_headers.items() if k != "x-entreprise-id"}

    def list_admins(self) -> Any:
        """Liste les administrateurs de plateforme.

        Appelle GET /admins-plateforme/.

        Returns:
            list: Liste des administrateurs (schéma AdminPlateformeRead).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (403 accès refusé si
                l'appelant n'est pas admin plateforme, 5xx serveur) ou API
                injoignable (APIUnavailableError).
        """
        return self.get("/admins-plateforme/")

    def search_user_by_email(self, email: str) -> Any:
        """Recherche des utilisateurs par fragment d'email.

        Appelle GET /admins-plateforme/recherche-utilisateur. La recherche est
        partielle et insensible à la casse ; l'API exige au moins 2 caractères.
        Sert à désigner l'utilisateur à promouvoir sans saisir son identifiant.

        Args:
            email (str): Fragment d'email à rechercher (au moins 2 caractères).
                Obligatoire.

        Returns:
            list: Utilisateurs correspondants (schéma AdminPlateformeRead) ;
            chaque entrée porte `admin_plateforme` indiquant s'il est déjà admin.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIValidationError: En cas de réponse 422 (fragment trop court, ...).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get(
            "/admins-plateforme/recherche-utilisateur", params={"email": email}
        )

    def promote_admin(self, utilisateur_id: int) -> Any:
        """Promeut un utilisateur au rang d'administrateur de plateforme.

        Appelle POST /admins-plateforme/{utilisateur_id}/promouvoir.

        Args:
            utilisateur_id (int): Identifiant de l'utilisateur à promouvoir.
                Obligatoire.

        Returns:
            dict: L'administrateur promu (schéma AdminPlateformeRead).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIValidationError: En cas de réponse 422 (utilisateur introuvable
                ou déjà admin, selon les règles de l'API).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(f"/admins-plateforme/{utilisateur_id}/promouvoir")

    def revoke_admin(self, utilisateur_id: int) -> Any:
        """Révoque les droits d'administrateur de plateforme d'un utilisateur.

        Appelle POST /admins-plateforme/{utilisateur_id}/revoquer. L'API refuse
        la révocation du compte protégé (racine) et l'auto-révocation.

        Args:
            utilisateur_id (int): Identifiant de l'administrateur à révoquer.
                Obligatoire.

        Returns:
            dict: L'utilisateur révoqué (schéma AdminPlateformeRead).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIValidationError: En cas de réponse 422 (compte protégé,
                auto-révocation, utilisateur non admin, selon l'API).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(f"/admins-plateforme/{utilisateur_id}/revoquer")
