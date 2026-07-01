"""Client HTTP pour les factures.

Couvre le domaine `factures` de l'API. Le contrat n'expose que trois routes
d'écriture (ni liste ni détail ne sont disponibles) :

- POST /factures/ : création d'une facture en brouillon (schéma FactureCreate).
- POST /factures/{facture_id}/valider : validation d'un brouillon.
- POST /factures/{facture_id}/avoir : génération d'un avoir.
"""

from typing import Any

from .base_client import BaseAPIClient


class FacturesClient(BaseAPIClient):
    """Client HTTP pour les factures.

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    Le contrat n'expose que la création de brouillon, la validation et la
    génération d'avoir : ni liste ni détail ne sont disponibles.
    """

    def create_invoice(self, payload: dict[str, Any]) -> Any:
        """Crée une facture en brouillon.

        Appelle POST /factures/ (schéma FactureCreate). Le champ `lignes`
        (liste de lignes de facture) est obligatoire dans le schéma.

        Args:
            payload (dict[str, Any]): Données de la facture, conformes au schéma
                FactureCreate. Obligatoire.

        Returns:
            dict: La facture créée en brouillon, telle que renvoyée par l'API
            (201).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.post("/factures/", data=payload)

    def validate_invoice(self, facture_id: int) -> Any:
        """Valide une facture en brouillon.

        Appelle POST /factures/{facture_id}/valider (sans corps de requête).

        Args:
            facture_id (int): Identifiant de la facture à valider. Obligatoire.

        Returns:
            dict: La facture validée, telle que renvoyée par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.post(f"/factures/{facture_id}/valider")

    def create_credit_note(self, facture_id: int) -> Any:
        """Génère un avoir à partir d'une facture.

        Appelle POST /factures/{facture_id}/avoir (sans corps de requête).

        Args:
            facture_id (int): Identifiant de la facture d'origine. Obligatoire.

        Returns:
            dict: L'avoir généré, tel que renvoyé par l'API (201).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.post(f"/factures/{facture_id}/avoir")
