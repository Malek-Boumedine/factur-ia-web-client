"""Client HTTP pour l'upload et le suivi de documents vers l'API Data.

Couvre les routes du domaine `documents` consommées par ce BFF :

- POST /documents/upload : dépôt d'un fichier (multipart, champ `file`),
  relayé vers l'API Data pour traitement (réponse 202 accepté).
- GET /documents/{id_document} : état d'un document (polling pendant
  l'extraction OCR, schéma `DocumentRead`).

Le webhook OCR (POST /documents/webhook/ocr) n'est volontairement pas exposé
ici : il est réservé à l'API IA et ne fait pas partie de ce BFF.
"""

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
