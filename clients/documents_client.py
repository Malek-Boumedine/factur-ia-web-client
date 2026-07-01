"""Client HTTP pour l'upload de documents vers l'API Data.

Couvre l'unique route d'upload du domaine `documents` :

- POST /documents/upload : dépôt d'un fichier (multipart, champ `file`),
  relayé vers l'API Data pour traitement (réponse 202 accepté).

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
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422
                validation).
        """
        files = {
            "file": (
                uploaded_file.name,
                uploaded_file.file,
                uploaded_file.content_type or "application/octet-stream",
            )
        }
        return self.post_file("/documents/upload", files=files)
