"""Client HTTP pour les entreprises (espaces de travail / tenants).

Couvre la création d'entreprise, utilisée par l'onboarding : un utilisateur
authentifié sans entreprise rattachée crée son espace et en devient le
propriétaire.

- POST /entreprises/ : création d'une entreprise (schéma EntrepriseCreate).

Cette route exige le JWT (Bearer) mais **pas** le header `x-entreprise-id` :
l'utilisateur n'a pas encore d'entreprise au moment de l'appel. Comme la session
ne contient pas encore `entreprise_id`, `BaseAPIClient.auth_headers` ne l'injecte
pas — l'appel part donc sans ce header, conformément au contrat.
"""

from typing import Any

from .base_client import BaseAPIClient


class EntreprisesClient(BaseAPIClient):
    """Client HTTP pour les entreprises (création de l'espace de travail)."""

    def create_entreprise(self, payload: dict[str, Any]) -> Any:
        """Crée une entreprise et rattache l'utilisateur courant comme propriétaire.

        Appelle POST /entreprises/ (schéma EntrepriseCreate). Champ obligatoire :
        `nom_entreprise` ; `siret` et `id_forme_juridique` sont optionnels.

        Args:
            payload (dict[str, Any]): Données conformes à EntrepriseCreate,
                produites par `EntrepriseForm.to_api_payload()`. Obligatoire.

        Returns:
            dict: L'entreprise créée (EntrepriseRead), dont la clé `id` sert à
            initialiser `entreprise_id` en session.

        Raises:
            TokenExpiredError: En cas de réponse 401 (session vidée).
            APIValidationError: En cas de réponse 422 ; `detail` porte les
                erreurs de validation à rattacher aux champs.
            APIClientError: Toute autre erreur API mappée, ou API injoignable
                (APIUnavailableError).
        """
        return self.post("/entreprises/", data=payload)
