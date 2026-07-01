"""Client HTTP pour les abonnements (offres/plans).

Couvre le domaine `abonnements` de l'API. Aucune de ces routes n'exige le
header `x-entreprise-id` (les offres sont globales, non liées à un tenant) :

- GET /abonnements/ : liste des abonnements disponibles.
- GET /abonnements/me : abonnement de l'entreprise courante.
- POST /abonnements/ : création d'un abonnement (schéma AbonnementCreate).
- PATCH /abonnements/{abonnement_id} : mise à jour partielle
  (schéma AbonnementUpdate).
- DELETE /abonnements/{abonnement_id} : suppression d'un abonnement.
"""

from typing import Any

from .base_client import BaseAPIClient


class AbonnementsClient(BaseAPIClient):
    """Client HTTP pour les abonnements (offres/plans).

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT est
    injecté automatiquement depuis la session. Ces routes n'exigent pas le
    header `x-entreprise-id` (offres globales) ; il reste transmis s'il est
    présent en session, sans effet.
    """

    def list_subscriptions(self) -> Any:
        """Liste les abonnements disponibles.

        Appelle GET /abonnements/.

        Returns:
            list: Liste des abonnements (dictionnaires) renvoyée par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.get("/abonnements/")

    def get_my_subscription(self) -> Any:
        """Récupère l'abonnement de l'entreprise courante.

        Appelle GET /abonnements/me.

        Returns:
            dict: L'abonnement de l'entreprise courante, tel que renvoyé par
            l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.get("/abonnements/me")

    def create_subscription(self, payload: dict[str, Any]) -> Any:
        """Crée un abonnement.

        Appelle POST /abonnements/ (schéma AbonnementCreate). Champ obligatoire
        du schéma : `libelle`.

        Args:
            payload (dict[str, Any]): Données de l'abonnement, conformes au
                schéma AbonnementCreate. Obligatoire.

        Returns:
            dict: L'abonnement créé, tel que renvoyé par l'API (201).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.post("/abonnements/", data=payload)

    def update_subscription(self, abonnement_id: int, payload: dict[str, Any]) -> Any:
        """Met à jour partiellement un abonnement.

        Appelle PATCH /abonnements/{abonnement_id} (schéma AbonnementUpdate,
        tous les champs optionnels).

        Args:
            abonnement_id (int): Identifiant de l'abonnement à modifier.
                Obligatoire.
            payload (dict[str, Any]): Champs partiels à mettre à jour, conformes
                au schéma AbonnementUpdate. Obligatoire.

        Returns:
            dict: L'abonnement mis à jour, tel que renvoyé par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.patch(f"/abonnements/{abonnement_id}", data=payload)

    def delete_subscription(self, abonnement_id: int) -> Any:
        """Supprime un abonnement.

        Appelle DELETE /abonnements/{abonnement_id}.

        Args:
            abonnement_id (int): Identifiant de l'abonnement à supprimer.
                Obligatoire.

        Returns:
            bool: `True` en cas de succès (réponse 204 sans contenu).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.delete(f"/abonnements/{abonnement_id}")
