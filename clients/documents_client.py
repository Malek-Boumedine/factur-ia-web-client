from .base_client import BaseAPIClient


class DocumentsClient(BaseAPIClient):
    def upload_document(self, uploaded_file):
        """Relaie un fichier uploadé (Django UploadedFile) vers l'API Data.

        Le contrat OpenAPI attend un champ multipart nommé `file`
        sur POST /documents/upload (réponse 202).
        """
        files = {
            "file": (
                uploaded_file.name,
                uploaded_file.file,
                uploaded_file.content_type or "application/octet-stream",
            )
        }
        return self.post_file("/documents/upload", files=files)
