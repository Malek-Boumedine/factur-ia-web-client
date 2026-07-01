from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.documents_client import DocumentsClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    TokenExpiredError,
)


def _contexte_upload() -> dict[str, object]:
    """Construit le contexte du template d'upload à partir des settings.

    Returns:
        dict: Limites d'upload exposées au template (taille max en octets et en
        Mo, extensions autorisées) pour l'affichage et la validation client.
    """
    taille_max = getattr(settings, "DOCUMENT_UPLOAD_MAX_SIZE", 10 * 1024 * 1024)
    extensions = getattr(
        settings,
        "DOCUMENT_UPLOAD_ALLOWED_EXTENSIONS",
        [".pdf", ".png", ".jpg", ".jpeg"],
    )
    return {
        "taille_max_octets": taille_max,
        "taille_max_mo": round(taille_max / (1024 * 1024)),
        "extensions_autorisees": ",".join(extensions),
    }


def upload_document_view(request: HttpRequest) -> HttpResponse:
    """Réceptionne un document, le valide, puis le relaie à l'API Data.

    Flux BFF : le fichier est validé côté serveur (type et taille, seule
    validation faisant autorité) puis transmis en multipart via la couche
    `clients/` sur POST /documents/upload. Rien n'est stocké côté Django. Une
    réponse 202 de l'API signifie que le document est accepté pour un traitement
    asynchrone (l'OCR n'est pas attendu ici).

    Args:
        request (HttpRequest): Requête Django. En POST, le fichier est lu depuis
            `request.FILES["file"]`. Obligatoire.

    Returns:
        HttpResponse: Redirection vers la page d'upload en cas de succès, sinon
        rendu du formulaire avec un message d'erreur.
    """
    if not request.session.get("is_authenticated"):
        return redirect("login")

    if request.method == "POST":
        fichier = request.FILES.get("file")
        taille_max = getattr(settings, "DOCUMENT_UPLOAD_MAX_SIZE", 10 * 1024 * 1024)
        types_autorises = getattr(
            settings,
            "DOCUMENT_UPLOAD_ALLOWED_TYPES",
            ["application/pdf", "image/png", "image/jpeg"],
        )

        # Validation serveur AVANT tout appel réseau : on n'appelle l'API que
        # si le fichier est présent, d'un type autorisé et sous la limite.
        if not fichier:
            messages.error(request, "Veuillez sélectionner un fichier.")
        elif fichier.size is None or fichier.size > taille_max:
            taille_max_mo = round(taille_max / (1024 * 1024))
            messages.error(
                request, f"Fichier trop volumineux (max {taille_max_mo} Mo)."
            )
        elif fichier.content_type not in types_autorises:
            messages.error(request, "Format non supporté (PDF, PNG ou JPEG attendu).")
        else:
            client = DocumentsClient(request)
            try:
                client.upload_document(fichier)
                # 202 Accepted : document reçu, traitement asynchrone à venir.
                messages.success(request, "Document reçu, traitement en cours.")
                return redirect("upload_document")
            except TokenExpiredError:
                return redirect("login")
            except APIValidationError as e:
                messages.error(request, str(e.detail or e.message))
            except APIUnavailableError:
                messages.error(
                    request,
                    "Service momentanément indisponible. Veuillez réessayer.",
                )
            except APIClientError as e:
                messages.error(request, str(e.message))

    return render(request, "core/upload.html", _contexte_upload())
