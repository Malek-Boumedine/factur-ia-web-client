import httpx
from django.contrib import messages
from django.shortcuts import redirect, render

from clients.base_client import TokenExpiredError
from clients.documents_client import DocumentsClient

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
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", "Erreur API.")
                except ValueError:
                    detail = f"Erreur API ({e.response.status_code})."
                messages.error(request, str(detail))
            except httpx.RequestError:
                messages.error(
                    request, "Impossible de contacter le serveur de documents."
                )

    return render(request, "core/upload.html")
