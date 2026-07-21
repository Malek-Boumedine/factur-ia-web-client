"""Client HTTP pour les factures.

Couvre le domaine `factures` de l'API :

- POST /factures/ : création d'une facture en brouillon (schéma FactureCreate).
- GET /factures/{facture_id} : détail d'une facture avec ses lignes
  (schéma FactureReadWithLignes), utilisé par le récap human-in-the-loop.
- POST /factures/{facture_id}/valider : validation d'un brouillon.
- POST /factures/{facture_id}/avoir : génération d'un avoir.

La liste des factures n'est pas encore exposée par le contrat.
"""

from typing import Any

from .base_client import BaseAPIClient


class FacturesClient(BaseAPIClient):
    """Client HTTP pour les factures.

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    Couvre la création de brouillon, le détail avec lignes, la validation et
    la génération d'avoir (la liste des factures n'est pas encore exposée).
    """

    def get_facture(self, facture_id: int) -> Any:
        """Récupère le détail d'une facture avec ses lignes.

        Appelle GET /factures/{facture_id} (schéma FactureReadWithLignes).
        L'API garantit l'isolation tenant : une facture d'une autre entreprise
        renvoie un 404.

        Args:
            facture_id (int): Identifiant de la facture à lire. Obligatoire.

        Returns:
            dict: La facture et ses lignes (`lignes`), telles que renvoyées
            par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Facture inexistante ou hors du tenant (404).
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get(f"/factures/{facture_id}")

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
