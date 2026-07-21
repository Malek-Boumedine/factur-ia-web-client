from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from clients.documents_client import DocumentsClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from core.views.auth import _guard_entreprise

# Cadence du polling de l'écran d'attente : une vérification toutes les 3 s,
# 40 tentatives maximum (~2 min) avant d'afficher la porte de sortie.
_POLL_INTERVAL_MS = 3000
_POLL_MAX_ATTEMPTS = 40

# Statuts renvoyés par l'API (enum StatutDocument du contrat OpenAPI).
_STATUT_TRAITE = "traité"
_STATUT_ERREUR = "erreur"

# Pseudo-statut côté BFF : API injoignable pendant le polling (le front garde
# le spinner et réessaie jusqu'au timeout au lieu de planter l'écran).
_STATUT_INDISPONIBLE = "indisponible"


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
    refus = _guard_entreprise(request)
    if refus:
        return refus

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
                reponse = client.upload_document(fichier)
                # 202 Accepted : le corps porte `id_document`, qui permet de
                # suivre l'extraction sur l'écran d'attente. Lecture défensive :
                # sans id exploitable, on retombe sur l'ancien comportement.
                document_id = (
                    reponse.get("id_document") if isinstance(reponse, dict) else None
                )
                if isinstance(document_id, int):
                    return redirect("document_attente", document_id=document_id)
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


def document_wait_view(request: HttpRequest, document_id: int) -> HttpResponse:
    """Affiche l'écran d'attente pendant l'extraction IA d'un document.

    Interroge une première fois l'API côté serveur pour connaître l'état
    initial : un document déjà traité redirige immédiatement vers le récap,
    un document introuvable renvoie vers la page de dépôt avec un message.
    Sinon, le template rend un spinner et un composant Alpine qui poll la vue
    JSON `document_status_view` jusqu'au verdict (pattern BFF : le navigateur
    ne parle jamais directement à l'API Data).

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        document_id (int): Identifiant du document suivi. Obligatoire.

    Returns:
        HttpResponse: Rendu de l'écran d'attente, ou redirection (récap si
        déjà traité, dépôt si introuvable, login si session expirée).
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    statut = "en_attente"
    nom_original = ""
    client = DocumentsClient(request)
    try:
        document = client.get_document(document_id)
        statut = document.get("statut") or "en_attente"
        nom_original = document.get("nom_original") or ""
        if statut == _STATUT_TRAITE and document.get("id_facture"):
            return redirect("facture_recap", facture_id=document["id_facture"])
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Document introuvable.")
        return redirect("upload_document")
    except APIClientError:
        # API injoignable ou en erreur : on affiche quand même l'écran, le
        # polling côté navigateur réessaiera jusqu'au timeout de sécurité.
        statut = _STATUT_INDISPONIBLE

    contexte = {
        "nom_original": nom_original,
        "polling_config": {
            "statut_initial": statut,
            "url_statut": reverse(
                "document_statut", kwargs={"document_id": document_id}
            ),
            "url_login": reverse("login"),
            "interval_ms": _POLL_INTERVAL_MS,
            "max_attempts": _POLL_MAX_ATTEMPTS,
        },
    }
    return render(request, "core/document_attente.html", contexte)


def document_status_view(request: HttpRequest, document_id: int) -> JsonResponse:
    """Relaie l'état d'un document au format JSON pour le polling Alpine.

    Vue BFF appelée en `fetch` par l'écran d'attente : elle interroge
    GET /documents/{id_document} via la couche `clients/` (JWT en session,
    jamais exposé au navigateur) et renvoie un contrat JSON minimal :
    `statut`, `id_facture`, `url_redirection` (récap si traité) et `message`.
    Les incidents transitoires (API injoignable, 5xx) sont traduits en
    pseudo-statut `indisponible` pour que le front continue de poller sans
    planter ; une session expirée renvoie 401 avec l'URL de login.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        document_id (int): Identifiant du document suivi. Obligatoire.

    Returns:
        JsonResponse: L'état du document, ou un statut d'erreur exploitable
        par le composant de polling.
    """
    if not request.session.get("is_authenticated") or not request.session.get(
        "entreprise_id"
    ):
        return JsonResponse(
            {"statut": "session_expiree", "url_redirection": reverse("login")},
            status=401,
        )

    client = DocumentsClient(request)
    try:
        document = client.get_document(document_id)
    except TokenExpiredError:
        return JsonResponse(
            {"statut": "session_expiree", "url_redirection": reverse("login")},
            status=401,
        )
    except ResourceNotFoundError:
        return JsonResponse(
            {"statut": _STATUT_ERREUR, "message": "Document introuvable."}
        )
    except APIClientError:
        # Injoignable ou erreur serveur : le front garde le spinner et
        # réessaiera à la prochaine itération (jusqu'au timeout de sécurité).
        return JsonResponse({"statut": _STATUT_INDISPONIBLE})

    statut = document.get("statut") or _STATUT_INDISPONIBLE
    id_facture = document.get("id_facture")
    url_redirection = None
    message = None
    if statut == _STATUT_TRAITE:
        if id_facture:
            url_redirection = reverse(
                "facture_recap", kwargs={"facture_id": id_facture}
            )
        else:
            # Traité sans facture associée : anomalie, traitée comme un échec.
            statut = _STATUT_ERREUR
            message = "L'analyse n'a pas produit de facture."

    return JsonResponse(
        {
            "statut": statut,
            "id_facture": id_facture,
            "url_redirection": url_redirection,
            "message": message,
        }
    )
