"""Client HTTP pour les factures.

Couvre le domaine `factures` de l'API :

- GET /factures/ : liste paginée avec recherche et filtres (enveloppe
  Page[FactureListItem]).
- GET /factures/statistiques : agrégations de facturation calculées en base
  (schéma StatistiquesFactures), pour le tableau de bord.
- POST /factures/ : création d'une facture en brouillon (schéma FactureCreate).
- GET /factures/{facture_id} : détail d'une facture avec ses lignes
  (schéma FactureReadWithLignes), utilisé par le récap human-in-the-loop.
- PATCH /factures/{facture_id} : modification d'un brouillon (schéma
  FactureUpdate), en-tête et remplacement complet des lignes.
- DELETE /factures/{facture_id} : suppression définitive d'un brouillon.
- POST /factures/{facture_id}/valider : validation d'un brouillon.
- POST /factures/{facture_id}/avoir : génération d'un avoir.
- GET /factures/{facture_id}/facturx : téléchargement du fichier Factur-X
  (PDF/A-3 + XML CII) d'une facture validée, en streaming.
- GET /factures/{facture_id}/facturx/conformite : rapport de conformité
  Factur-X (schéma RapportConformiteFacturX), sans génération de fichier.
"""

from collections.abc import Iterator
from typing import Any

from .base_client import BaseAPIClient


class FacturesClient(BaseAPIClient):
    """Client HTTP pour les factures.

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    Couvre la liste paginée, les statistiques agrégées, la création de
    brouillon, le détail avec lignes, la modification et la suppression d'un
    brouillon, la validation et la génération d'avoir.
    """

    def list_invoices(
        self,
        search: str | None = None,
        statut: str | None = None,
        type_facture: str | None = None,
        id_client: int | None = None,
        date_emission_min: str | None = None,
        date_emission_max: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Any:
        """Liste paginée des factures de l'entreprise active.

        Appelle GET /factures/ (enveloppe `Page[FactureListItem]` de la forme
        ``{"items": [...], "total": N, "skip": ..., "limit": ...}``), les plus
        récentes d'abord. Chaque item expose `nom_destinataire`, déjà résolu
        par l'API (snapshot figé pour une facture validée, raison sociale du
        client lié pour un brouillon). Les paramètres optionnels ne sont
        transmis en query string que lorsqu'ils sont fournis.

        Args:
            search (str | None): Recherche sur le numéro de facture, la
                référence de commande ou la raison sociale du client.
                Optionnel.
            statut (str | None): Filtre sur le libellé du statut
                (ex. « Brouillon », « Validée »). Optionnel.
            type_facture (str | None): Filtre sur le type de document
                (« facture » ou « avoir »). Optionnel.
            id_client (int | None): Filtre sur le client destinataire.
                Optionnel.
            date_emission_min (str | None): Borne basse (incluse) sur la date
                d'émission, au format ISO `AAAA-MM-JJ`. Optionnel.
            date_emission_max (str | None): Borne haute (incluse) sur la date
                d'émission, au format ISO `AAAA-MM-JJ`. Optionnel.
            skip (int): Décalage de pagination (offset). Défaut 0.
            limit (int): Nombre maximum d'éléments à renvoyer (max 100 côté
                API). Défaut 100.

        Returns:
            dict: L'enveloppe paginée `Page[FactureListItem]` renvoyée par
            l'API, avec les clés `items` (liste) et `total` (nombre total,
            tous filtres appliqués).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if search:
            params["search"] = search
        if statut:
            params["statut"] = statut
        if type_facture:
            params["type_facture"] = type_facture
        if id_client is not None:
            params["id_client"] = id_client
        if date_emission_min:
            params["date_emission_min"] = date_emission_min
        if date_emission_max:
            params["date_emission_max"] = date_emission_max
        return self.get("/factures/", params=params)

    def get_statistiques(
        self,
        date_min: str | None = None,
        date_max: str | None = None,
        devise: str | None = None,
        limite_top_clients: int | None = None,
    ) -> Any:
        """Agrégations de facturation de l'entreprise active.

        Appelle GET /factures/statistiques (schéma StatistiquesFactures) : tout
        est calculé en base (SUM/COUNT/GROUP BY), la réponse est donc exacte
        sans pagination ni plafond. Le périmètre couvre les seuls documents
        émis de la période et de la devise demandées ; les brouillons sont
        comptés à part dans `brouillons`, et les avoirs sont soustraits de tous
        les montants.

        Attention : `paiement` et `brouillons` sont eux aussi bornés par la
        période — une fenêtre étroite masque les impayés et les brouillons plus
        anciens. Sans dates, l'API applique 12 mois glissants.

        Args:
            date_min (str | None): Borne basse (incluse) sur la date
                d'émission, au format ISO `AAAA-MM-JJ`. Optionnel : par défaut
                l'API prend le premier jour du mois, 11 mois avant `date_max`.
            date_max (str | None): Borne haute (incluse) sur la date
                d'émission, au format ISO `AAAA-MM-JJ`. Optionnel : par défaut
                aujourd'hui côté API.
            devise (str | None): Devise des montants agrégés (code ISO 4217 sur
                3 lettres). Optionnel, `EUR` par défaut côté API ; les
                documents d'une autre devise sont exclus des totaux et
                signalés dans `devises_exclues`.
            limite_top_clients (int | None): Nombre de clients renvoyés dans
                `top_clients` (1 à 20). Optionnel, 5 par défaut côté API.

        Returns:
            dict: Les agrégations (schéma StatistiquesFactures) : `periode`,
            `devise`, `totaux`, `par_statut`, `par_mois`, `top_clients`,
            `paiement`, `devises_exclues` et `brouillons`. Les montants sont
            des chaînes décimales.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        params: dict[str, Any] = {}
        if date_min:
            params["date_min"] = date_min
        if date_max:
            params["date_max"] = date_max
        if devise:
            params["devise"] = devise
        if limite_top_clients is not None:
            params["limite_top_clients"] = limite_top_clients
        return self.get("/factures/statistiques", params=params)

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

    def update_invoice(self, facture_id: int, payload: dict[str, Any]) -> Any:
        """Modifie un brouillon de facture.

        Appelle PATCH /factures/{facture_id} (schéma FactureUpdate) : champs
        d'en-tête et, si `lignes` est fourni, remplacement complet des lignes
        avec recalcul des totaux par l'API. Seuls les brouillons sont
        modifiables : l'API refuse toute modification d'une facture validée
        (inaltérabilité légale).

        Args:
            facture_id (int): Identifiant du brouillon à modifier. Obligatoire.
            payload (dict[str, Any]): Champs à modifier, conformes au schéma
                FactureUpdate (PATCH partiel : les clés absentes restent
                inchangées). Obligatoire.

        Returns:
            dict: La facture mise à jour avec ses lignes (schéma
            FactureReadWithLignes), telle que renvoyée par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Facture inexistante ou hors du tenant (404).
            ResourceConflictError: Facture qui n'est plus un brouillon (409).
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.patch(f"/factures/{facture_id}", data=payload)

    def delete_invoice(self, facture_id: int) -> Any:
        """Supprime définitivement un brouillon de facture.

        Appelle DELETE /factures/{facture_id} : le brouillon et ses lignes
        sont supprimés, mais le document source et son extraction OCR sont
        conservés côté API (trace). Seuls les brouillons sont supprimables :
        une facture validée est immuable (inaltérabilité légale) et l'API
        refuse sa suppression.

        Args:
            facture_id (int): Identifiant du brouillon à supprimer.
                Obligatoire.

        Returns:
            bool: `True` sur 204 (suppression effectuée).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Facture inexistante ou hors du tenant (404).
            ResourceConflictError: Facture qui n'est plus un brouillon (409).
            APIClientError: Toute autre erreur API mappée (5xx serveur) ou
                API injoignable (APIUnavailableError).
        """
        return self.delete(f"/factures/{facture_id}")

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

    def download_facturx(
        self, facture_id: int
    ) -> tuple[Iterator[bytes], str, str | None]:
        """Télécharge le fichier Factur-X d'une facture validée, en streaming.

        Relais de GET /factures/{facture_id}/facturx : le PDF/A-3 (XML CII
        embarqué, profil MINIMUM) n'est jamais chargé en mémoire, il est
        consommé par morceaux pour être renvoyé au navigateur par la vue BFF.
        La génération est idempotente côté API : le fichier est reconstruit à
        chaque appel depuis les données figées à la validation.

        Args:
            facture_id (int): Identifiant de la facture. Obligatoire.

        Returns:
            tuple: Le triplet `(chunks, content_type, content_disposition)`
            renvoyé par `get_stream` (générateur de morceaux binaires, type
            MIME, en-tête `Content-Disposition` de l'API ou `None`).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Facture absente ou hors du tenant
                (404 indistinct).
            ResourceConflictError: Facture en brouillon ou donnée obligatoire
                du XML manquante, ex. SIRET émetteur absent (409, détail de
                l'API conservé).
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get_stream(f"/factures/{facture_id}/facturx")

    def get_conformity_report(self, facture_id: int) -> Any:
        """Récupère le rapport de conformité Factur-X d'une facture validée.

        Appelle GET /factures/{facture_id}/facturx/conformite : l'API vérifie
        les règles du profil MINIMUM (données obligatoires, cohérence des
        totaux, validité des SIRET) sans générer de fichier. Les erreurs
        bloquent la génération/transmission ; les avertissements sont
        informatifs et laissent `conforme` à vrai.

        Args:
            facture_id (int): Identifiant de la facture. Obligatoire.

        Returns:
            dict: Le rapport (schéma RapportConformiteFacturX) : `conforme`
            (bool), `erreurs` et `avertissements` (listes de problèmes
            portant `champ`, `code` et `message` en français).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Facture absente ou hors du tenant
                (404 indistinct).
            ResourceConflictError: Facture en brouillon (409) — le rapport
                n'a de sens que sur des données figées à la validation.
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get(f"/factures/{facture_id}/facturx/conformite")
