from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    JsonResponse,
    QueryDict,
    StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse

from clients.documents_client import DocumentsClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from core.pagination import (
    PAGE_SIZE,
    base_querystring,
    build_pagination,
    parse_page,
)
from core.views.auth import _MSG_INDISPONIBLE, _guard_entreprise

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

# Onglets de la liste des documents : valeur du query param `statut` (clés
# ASCII, sûres en URL) -> valeur de l'enum StatutDocument attendue par l'API
# (None = pas de filtre, onglet « Tous »).
_STATUS_TABS: dict[str, str | None] = {
    "tous": None,
    "en_attente": "en_attente",
    "en_cours": "en_cours",
    "traites": _STATUT_TRAITE,
    "erreur": _STATUT_ERREUR,
}
_DEFAULT_STATUS_TAB = "tous"

# Paramètres d'état de la liste des documents, seuls conservés lors du
# réencodage de la query string de retour (liste blanche).
_LIST_STATE_PARAMS = ("statut", "page")


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


def _parse_datetime(raw: object) -> datetime | None:
    """Convertit un horodatage ISO de l'API en datetime.

    Le filtre `date` des templates Django ignore les chaînes brutes : la
    conversion doit se faire côté vue. Lecture défensive : toute valeur
    absente ou mal formée devient `None` (affichée « — »).

    Args:
        raw (object): Valeur brute de `date_chargement` (chaîne ISO 8601
            attendue, possiblement absente ou d'une autre forme). Obligatoire.

    Returns:
        datetime | None: L'horodatage converti, ou `None` si inexploitable.
    """
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def documents_list_view(request: HttpRequest) -> HttpResponse:
    """Affiche la liste paginée des documents uploadés, filtrable par statut.

    Vue d'ensemble des dépôts de l'entreprise active (GET /documents/, les
    plus récents d'abord). Le filtre s'exprime en onglets (query param
    `statut` : « tous » par défaut, ou une clé de `_STATUS_TABS` mappée vers
    l'enum StatutDocument de l'API) ; l'état complet est porté par l'URL, la
    page est donc partageable et rechargeable. La pagination réutilise
    `core.pagination` (les liens de page conservent l'onglet via
    `base_query` ; les liens d'onglets repartent en première page).

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.

    Returns:
        HttpResponse: Rendu de la liste (vide avec message d'erreur si l'API
        est indisponible), ou redirection vers le login si session expirée.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    tab = request.GET.get("statut", _DEFAULT_STATUS_TAB)
    if tab not in _STATUS_TABS:
        tab = _DEFAULT_STATUS_TAB
    page = parse_page(request.GET.get("page"))
    skip = (page - 1) * PAGE_SIZE

    items: list = []
    total = 0
    try:
        result = DocumentsClient(request).list_documents(
            statut=_STATUS_TABS[tab],
            skip=skip,
            limit=PAGE_SIZE,
        )
        if isinstance(result, dict):
            items = result.get("items", [])
            total = result.get("total", 0)
    except TokenExpiredError:
        return redirect("login")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        messages.error(
            request, f"Erreur lors du chargement des documents ({e.status_code})."
        )

    # Horodatage ISO -> datetime, pour le formatage `d/m/Y H:i` du template.
    for item in items:
        item["date_chargement_dt"] = _parse_datetime(item.get("date_chargement"))

    pagination = build_pagination(page, total)

    context = {
        "items": items,
        "total": total,
        "statut": tab,
        "base_query": base_querystring(request),
        # Query string complète, embarquée par les forms de suppression pour
        # revenir sur la liste dans le même état.
        "current_query": request.GET.urlencode(),
        **pagination,
    }
    return render(request, "core/documents.html", context)


def document_file_view(request: HttpRequest, document_id: int) -> HttpResponseBase:
    """Relaie le fichier original d'un document vers le navigateur (BFF).

    Le navigateur ne tape jamais l'API Data : cette vue récupère le flux de
    GET /documents/{id_document}/fichier via la couche `clients/` (JWT
    serveur-side) et le renvoie tel quel en `StreamingHttpResponse` — rien
    n'est chargé en mémoire ni stocké côté Django. Le type MIME et le
    `Content-Disposition` (`inline`, affichage dans l'onglet) de l'API sont
    relayés au navigateur.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        document_id (int): Identifiant du document à consulter. Obligatoire.

    Returns:
        HttpResponseBase: Le flux du fichier (streaming), ou une redirection
        vers la liste avec un message (introuvable, API indisponible), ou
        vers le login si session expirée.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    try:
        chunks, content_type, content_disposition = DocumentsClient(
            request
        ).get_document_file(document_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        # 404 indistinct côté API (document absent, fichier manquant ou hors
        # tenant) : message clair + retour liste, pas de page blanche.
        messages.error(request, "Document ou fichier introuvable.")
        return redirect("documents")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("documents")
    except APIClientError:
        messages.error(request, "Erreur lors de l'ouverture du document.")
        return redirect("documents")

    response = StreamingHttpResponse(chunks, content_type=content_type)
    response["Content-Disposition"] = content_disposition or "inline"
    return response


def _safe_list_query(raw: object) -> str:
    """Réencode une query string de retour vers la liste des documents.

    Ne conserve que les paramètres d'état connus (`_LIST_STATE_PARAMS`) : la
    valeur soumise par le formulaire n'est jamais réutilisée telle quelle
    dans la redirection. Le paramètre `statut` est en outre revalidé contre
    les onglets connus (`_STATUS_TABS`) pour ne jamais rediriger vers un
    filtre inexistant.

    Args:
        raw (object): Query string soumise (champ hidden `retour`),
            possiblement absente ou d'une autre forme. Obligatoire.

    Returns:
        str: Query string urlencodée ne contenant que les paramètres connus,
        ou chaîne vide.
    """
    parsed = QueryDict(raw if isinstance(raw, str) else "")
    params = QueryDict(mutable=True)
    for key in _LIST_STATE_PARAMS:
        value = parsed.get(key)
        if not value:
            continue
        if key == "statut" and value not in _STATUS_TABS:
            continue
        params[key] = value
    return params.urlencode()


def document_delete_view(request: HttpRequest, document_id: int) -> HttpResponse:
    """Supprime un document depuis la liste (POST uniquement).

    Relaie DELETE /documents/{id_document} via la couche `clients/` (pattern
    BFF : le navigateur ne touche jamais l'API). La suppression est
    définitive côté API (document, extractions OCR et fichier physique) ; la
    confirmation est demandée en amont par le formulaire de la liste. L'API
    refuse en 409 si une facture — brouillon ou validée — référence le
    document : le message invite alors à supprimer d'abord la facture. Dans
    tous les cas, redirige vers la liste des documents dans l'état transmis
    par le champ `retour` (onglet, page — réencodé en liste blanche). Un GET
    ne déclenche rien.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        document_id (int): Identifiant du document à supprimer. Obligatoire.

    Returns:
        HttpResponse: Redirection vers la liste des documents (avec message
        de succès ou d'erreur), ou vers le login si session expirée.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    query = _safe_list_query(request.POST.get("retour"))
    list_url = reverse("documents") + (f"?{query}" if query else "")

    if request.method != "POST":
        return redirect(list_url)

    try:
        DocumentsClient(request).delete_document(document_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(
            request, "Document introuvable — il a peut-être déjà été supprimé."
        )
    except ResourceConflictError as e:
        messages.error(
            request,
            str(
                e.detail
                or "Une facture est liée à ce document : supprimez d'abord "
                "la facture avant de supprimer le document."
            ),
        )
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        messages.error(request, str(e.message))
    else:
        messages.success(request, "Document supprimé.")
    return redirect(list_url)
