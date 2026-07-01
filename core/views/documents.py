from django.contrib import messages
from django.shortcuts import redirect, render

from clients.documents_client import DocumentsClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    TokenExpiredError,
)

# Garde-fous d'upload (le backend reste l'autorité finale).
TAILLE_MAX = 10 * 1024 * 1024  # 10 Mo
TYPES_AUTORISES = {"application/pdf", "image/png", "image/jpeg"}


def upload_document_view(request):
    if not request.session.get("is_authenticated"):
        return redirect("login")

    if request.method == "POST":
        fichier = request.FILES.get("file")

        # Validation serveur avant de relayer vers l'API.
        if not fichier:
            messages.error(request, "Veuillez sélectionner un fichier.")
        elif fichier.size > TAILLE_MAX:
            messages.error(request, "Fichier trop volumineux (max 10 Mo).")
        elif fichier.content_type not in TYPES_AUTORISES:
            messages.error(request, "Format non supporté (PDF, PNG ou JPEG attendu).")
        else:
            client = DocumentsClient(request)
            try:
                client.upload_document(fichier)
                messages.success(
                    request,
                    "Document envoyé. Le traitement IA est en cours.",
                )
                return redirect("upload_document")
            except TokenExpiredError:
                return redirect("login")
            except APIValidationError as e:
                messages.error(request, str(e.detail or e.message))
            except APIUnavailableError:
                messages.error(
                    request, "Impossible de contacter le serveur de documents."
                )
            except APIClientError as e:
                messages.error(request, str(e.message))

    return render(request, "core/upload.html")
