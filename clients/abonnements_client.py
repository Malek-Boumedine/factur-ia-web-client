"""Client HTTP pour les abonnements (offres/plans).

Couvre le domaine `abonnements` de l'API :

- GET /abonnements/ : liste des abonnements disponibles.
- GET /abonnements/me : abonnement de l'entreprise courante.
- POST /abonnements/me/changer : changement de plan de l'entreprise active.
- POST /abonnements/ : création d'un abonnement (schéma AbonnementCreate).
- PATCH /abonnements/{abonnement_id} : mise à jour partielle
  (schéma AbonnementUpdate).
- DELETE /abonnements/{abonnement_id} : suppression d'un abonnement.

Les routes des offres sont globales (le header `x-entreprise-id` reste
transmis s'il est en session, sans effet). Exception : POST
/abonnements/me/changer EXIGE ce header — il désigne l'entreprise dont le
plan est changé.
"""

from typing import Any

from .base_client import BaseAPIClient


class AbonnementsClient(BaseAPIClient):
    """Client HTTP pour les abonnements (offres/plans).

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    Les routes des offres sont globales (header tenant sans effet), sauf le
    changement de plan (`change_plan`) qui l'exige pour cibler l'entreprise.
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
        """Liste les abonnements/entreprises rattachés à l'utilisateur courant.

        Appelle GET /abonnements/me. La route renvoie une **liste** (un élément
        par entreprise rattachée, chacun portant `id_entreprise`) ; elle est
        vide si l'utilisateur n'a encore aucun espace de travail (cas onboarding).

        Returns:
            list: Les abonnements de l'utilisateur, tels que renvoyés par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.get("/abonnements/me")

    def change_plan(self, abonnement_id: int) -> Any:
        """Change le plan d'abonnement de l'entreprise active.

        Appelle POST /abonnements/me/changer (schéma ChangementPlanRequest).
        L'entreprise ciblée est TOUJOURS celle du header `x-entreprise-id`
        (injecté depuis la session) ; l'action est réservée côté API aux
        administrateurs de cette entreprise.

        Args:
            abonnement_id (int): Identifiant du plan d'abonnement cible.
                Obligatoire.

        Returns:
            dict: La nouvelle souscription active (EntrepriseAbonnementRead)
            renvoyée par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Plan cible introuvable (404).
            ResourceConflictError: Entreprise déjà sur ce plan, ou trop
                d'utilisateurs actifs pour le plan cible (409, message
                métier dans `detail`).
            APIClientError: Toute autre erreur API mappée (403 non membre ou
                non admin de l'entreprise, 422 validation, 5xx serveur) ou
                API injoignable (APIUnavailableError).
        """
        return self.post(
            "/abonnements/me/changer", data={"id_abonnement": abonnement_id}
        )

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
