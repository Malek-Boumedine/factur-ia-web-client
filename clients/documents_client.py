"""Client HTTP pour l'upload et le suivi de documents vers l'API Data.

Couvre les routes du domaine `documents` consommées par ce BFF :

- POST /documents/upload : dépôt d'un fichier (multipart, champ `file`),
  relayé vers l'API Data pour traitement (réponse 202 accepté).
- GET /documents/ : liste paginée des documents de l'entreprise active
  (schéma `Page[DocumentRead]`, filtre par statut optionnel).
- GET /documents/{id_document} : état d'un document (polling pendant
  l'extraction OCR, schéma `DocumentRead`).
- GET /documents/{id_document}/fichier : fichier original (PDF/image) en
  streaming, relayé au navigateur par la vue BFF de consultation.
- DELETE /documents/{id_document} : suppression définitive d'un document
  (204), refusée en 409 si une facture le référence.

Le webhook OCR (POST /documents/webhook/ocr) n'est volontairement pas exposé
ici : il est réservé à l'API IA et ne fait pas partie de ce BFF.
"""

from collections.abc import Iterator
from typing import Any

from django.core.files.uploadedfile import UploadedFile

from .base_client import BaseAPIClient


class DocumentsClient(BaseAPIClient):
    """Client HTTP pour le relais d'upload de documents.

    Hérite de `BaseAPIClient` et réutilise `post_file` (multipart) ; le JWT et
    le header `x-entreprise-id` sont injectés automatiquement depuis la session.
    """

    def upload_document(self, uploaded_file: UploadedFile) -> Any:
        """Relaie un fichier uploadé (Django UploadedFile) vers l'API Data.

        Le contrat OpenAPI attend un champ multipart nommé `file`
        sur POST /documents/upload (réponse 202).

        Args:
            uploaded_file (UploadedFile): Fichier reçu côté Django
                (`request.FILES`). Ses attributs `name`, `file` et
                `content_type` sont transmis dans la partie multipart `file`.
                Obligatoire.

        Returns:
            dict: Le corps JSON renvoyé par l'API (réponse 202, upload accepté).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        files = {
            "file": (
                uploaded_file.name,
                uploaded_file.file,
                uploaded_file.content_type or "application/octet-stream",
            )
        }
        return self.post_file("/documents/upload", files=files)

    def get_document(self, document_id: int) -> Any:
        """Récupère l'état d'un document (GET /documents/{id_document}).

        Utilisé pour le polling de l'écran d'attente pendant l'extraction :
        le `statut` évolue de `en_attente` à `en_cours` puis `traité` ou
        `erreur` ; `id_facture` est renseigné quand le document est traité.

        Args:
            document_id (int): Identifiant du document suivi. Obligatoire.

        Returns:
            dict: Le corps JSON `DocumentRead` (`id`, `nom_original`, `statut`,
            `date_chargement`, `id_facture`).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Document inexistant ou hors du tenant (404).
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get(f"/documents/{document_id}")

    def list_documents(
        self,
        statut: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Any:
        """Liste les documents uploadés de l'entreprise (GET /documents/).

        Les documents sont renvoyés les plus récents d'abord (tri côté API),
        dans le périmètre de l'entreprise active (isolation tenant).

        Args:
            statut (str | None): Filtre sur le statut (enum `StatutDocument` :
                `en_attente`, `en_cours`, `traité`, `erreur`). Optionnel,
                `None` par défaut (tous les statuts).
            skip (int): Nombre d'éléments à ignorer (offset). Défaut 0.
            limit (int): Nombre maximum d'éléments renvoyés (1 à 100).
                Défaut 100.

        Returns:
            dict: Le corps JSON `Page[DocumentRead]` (`items`, `total`,
            `skip`, `limit`).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if statut is not None:
            params["statut"] = statut
        return self.get("/documents/", params=params)

    def get_document_file(
        self, document_id: int
    ) -> tuple[Iterator[bytes], str, str | None]:
        """Récupère le fichier original d'un document, en streaming.

        Relais de GET /documents/{id_document}/fichier : le corps binaire
        (PDF ou image) n'est jamais chargé en mémoire, il est consommé par
        morceaux pour être renvoyé au navigateur par la vue BFF.

        Args:
            document_id (int): Identifiant du document. Obligatoire.

        Returns:
            tuple: Le triplet `(chunks, content_type, content_disposition)`
            renvoyé par `get_stream` (générateur de morceaux binaires, type
            MIME, en-tête `Content-Disposition` de l'API ou `None`).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Document ou fichier absent, ou hors du
                tenant (404 indistinct).
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get_stream(f"/documents/{document_id}/fichier")

    def delete_document(self, document_id: int) -> Any:
        """Supprime définitivement un document uploadé.

        Appelle DELETE /documents/{id_document} : le document, ses extractions
        OCR et son fichier physique sont supprimés côté API. L'API refuse en
        409 si une facture — brouillon ou validée — référence le document :
        le brouillon doit être supprimé d'abord ; une facture validée,
        immuable, impose de conserver le document (trace comptable).

        Args:
            document_id (int): Identifiant du document à supprimer.
                Obligatoire.

        Returns:
            bool: `True` sur 204 (suppression effectuée).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Document inexistant ou hors du tenant (404).
            ResourceConflictError: Facture référençant le document (409, le
                message `detail` de l'API est conservé).
            APIClientError: Toute autre erreur API mappée (5xx serveur) ou
                API injoignable (APIUnavailableError).
        """
        return self.delete(f"/documents/{document_id}")
