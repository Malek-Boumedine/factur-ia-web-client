"""Vues du domaine factures.

Liste des factures en deux onglets (brouillons / validées) avec recherche,
filtres sur la date d'émission et pagination, suppression d'un brouillon
depuis la liste (POST relayant le DELETE, confirmation en amont), et récapitulatif
human-in-the-loop d'un brouillon : affiche les données extraites par l'OCR
dans un formulaire éditable, pour relecture et correction avant validation.
La soumission enregistre les corrections via PATCH /factures/{facture_id}
(en-tête + remplacement complet des lignes), puis, selon l'action choisie,
valide le brouillon avec une vérification SIRENE non bloquante du SIRET
destinataire.

Le récap porte aussi le rattachement du client destinataire (requis pour
valider) : si le brouillon n'a pas d'`id_client`, un encart propose de
rattacher un client existant trouvé par SIRET dans le référentiel, ou de
créer la fiche via une recherche SIRENE (fenêtre de création pré-remplie,
POST /clients/ puis PATCH `id_client`).

S'y ajoute l'aperçu mis en forme d'une facture validée : page en lecture
seule stricte présentée comme une vraie facture (en-tête émetteur /
destinataire depuis le snapshot figé, tableau des prestations, totaux,
pied de page paiement), socle du futur export PDF/Factur-X.
"""

from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse

from clients.clients_client import ClientsClient
from clients.entreprises_client import EntreprisesClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from clients.factures_client import FacturesClient
from clients.produits_client import ProduitsClient
from clients.taux_tva_client import TauxTvaClient
from core.pagination import (
    PAGE_SIZE,
    base_querystring,
    build_pagination,
    parse_page,
)
from core.views.auth import _MSG_INDISPONIBLE, _guard_entreprise

# Champs usuels d'un snapshot client (objet libre du contrat) et leurs
# libellés d'affichage : lecture défensive, seuls les champs présents et non
# vides sont montrés.
_SNAPSHOT_LABELS = [
    ("raison_sociale", "Raison sociale"),
    ("siret", "SIRET"),
    ("numero_tva", "N° TVA"),
    ("adresse", "Adresse"),
    ("adresse_complement", "Complément d'adresse"),
    ("code_postal", "Code postal"),
    ("ville", "Ville"),
    ("email", "Email"),
    ("telephone", "Téléphone"),
]

# Champs d'en-tête éditables du formulaire récap, alignés sur le schéma
# FactureUpdate du contrat. Les autres clés du schéma (id_client,
# type_facture) n'ont pas de champ dans le formulaire : omises du payload,
# elles restent inchangées (PATCH partiel).
_EDITABLE_HEADER_FIELDS = (
    "date_emission",
    "date_echeance",
    "devise",
    "siret_emetteur",
    "siret_destinataire",
    "mode_paiement",
    "iban",
    "reference_commande",
    "notes",
)

# Champs SIRET du formulaire : la saisie usuelle avec espaces
# (« 123 456 789 00012 ») est normalisée avant envoi, l'API n'acceptant que
# des chiffres (14 max, incomplet accepté, vide = effacement).
_SIRET_FIELDS = ("siret_emetteur", "siret_destinataire")

# Champs éditables d'une ligne (préfixés `ligne-N-` dans le formulaire),
# alignés sur le schéma FactureLigneCreate.
_LINE_FIELDS = ("designation", "quantite", "unite", "prix_unitaire_ht", "id_taux_tva")

# Onglets de la liste des factures : valeur du query param `onglet` -> libellé
# de statut attendu par l'API (query param `statut` de GET /factures/).
_TABS = {
    "brouillons": "Brouillon",
    "validees": "Validée",
}
_DEFAULT_TAB = "brouillons"

# Paramètres d'état de la liste des factures (onglet, recherche, filtres,
# page) : seule cette liste blanche est réencodée dans les redirections de
# retour vers la liste — jamais une query string arbitraire.
_LIST_STATE_PARAMS = ("onglet", "q", "date_min", "date_max", "page")


def _snapshot_items(snapshot: object) -> list[tuple[str, str]]:
    """Extrait du snapshot client les champs affichables (libellé, valeur).

    Args:
        snapshot (object): Contenu de `snapshot_client` (objet JSON libre,
            possiblement `None` ou d'une autre forme). Obligatoire.

    Returns:
        list[tuple[str, str]]: Paires (libellé FR, valeur) des champs connus,
        présents et non vides, dans l'ordre d'affichage. Vide si le snapshot
        est absent ou inexploitable.
    """
    if not isinstance(snapshot, dict):
        return []
    items = []
    for key, label in _SNAPSHOT_LABELS:
        value = snapshot.get(key)
        if value not in (None, ""):
            items.append((label, str(value)))
    return items


def _format_rate(value: Any) -> str | None:
    """Formate un taux de TVA pour affichage (« 20 », « 5.5 »), `None` si absent.

    Les taux du référentiel sont des chaînes décimales (« 20.00 ») : les
    zéros de fin et le point superflu sont retirés pour l'affichage.
    """
    text = str(value or "").strip()
    if not text:
        return None
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _to_int(value: Any) -> int | None:
    """Convertit une valeur en entier, ou `None` si impossible."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean_optional(value: Any) -> str | None:
    """Nettoie un champ optionnel : chaîne sans espaces superflus, `None` si vide."""
    text = str(value or "").strip()
    return text or None


def _normalize_siret(value: Any) -> str:
    """Normalise un SIRET pour comparaison : espaces retirés, chaîne vide si absent."""
    return str(value or "").strip().replace(" ", "")


def _normalize_decimal(value: Any) -> str:
    """Normalise un montant saisi en chaîne décimale (virgule → point, espaces retirés)."""
    text = str(value or "").strip()
    # Espace simple, insécable (U+00A0) et fine insécable (U+202F),
    # fréquentes dans les montants extraits par OCR.
    for space in (" ", "\u00a0", "\u202f"):
        text = text.replace(space, "")
    return text.replace(",", ".")


def _build_update_payload(post: QueryDict) -> dict[str, Any]:
    """Reconstruit le payload FactureUpdate depuis le formulaire récap.

    En-tête : champs éditables du formulaire, chaîne vide → `None` (efface la
    valeur côté API). Lignes : reconstruites depuis la convention
    `ligne-N-champ` et `lignes_count` (remplacement complet côté API),
    montants en chaînes décimales normalisées, `id_taux_tva` en entier,
    `ordre` = position dans le formulaire. Une valeur non convertible est
    envoyée telle quelle : l'API la refuse en 422 et l'erreur est rattachée
    au champ concerné.

    Args:
        post (QueryDict): Données POST du formulaire récap. Obligatoire.

    Returns:
        dict[str, Any]: Payload conforme au schéma FactureUpdate (`lignes`
        omis si le formulaire n'en contient aucune).
    """
    payload: dict[str, Any] = {
        field: _clean_optional(post.get(field)) for field in _EDITABLE_HEADER_FIELDS
    }
    for field in _SIRET_FIELDS:
        if payload[field]:
            payload[field] = payload[field].replace(" ", "")
    count = _to_int(post.get("lignes_count")) or 0
    lines = []
    for index in range(count):
        prefix = f"ligne-{index}-"
        tax_id = _to_int(post.get(prefix + "id_taux_tva"))
        lines.append(
            {
                "designation": str(post.get(prefix + "designation") or "").strip(),
                "quantite": _normalize_decimal(post.get(prefix + "quantite")),
                "unite": _clean_optional(post.get(prefix + "unite")),
                "prix_unitaire_ht": _normalize_decimal(
                    post.get(prefix + "prix_unitaire_ht")
                ),
                "id_taux_tva": (
                    tax_id
                    if tax_id is not None
                    else post.get(prefix + "id_taux_tva", "")
                ),
                "ordre": index + 1,
            }
        )
    if lines:
        payload["lignes"] = lines
    return payload


def _map_validation_errors(
    detail: Any,
) -> tuple[dict[str, str], dict[int, dict[str, str]], list[str]]:
    """Traduit le détail 422 de l'API en erreurs par champ du formulaire récap.

    Même logique que `_appliquer_erreurs_api`, adaptée au formulaire construit
    à la main (pas de Form Django) : les `loc` d'en-tête sont rattachés au
    champ du même nom, les `loc` de lignes (`["body", "lignes", N, "champ"]`)
    à la ligne N, le reste part en erreurs globales.

    Args:
        detail (Any): Contenu du champ `detail` de la réponse 422 (liste
            d'objets `{loc, msg}` FastAPI, ou chaîne). Obligatoire.

    Returns:
        tuple: (erreurs d'en-tête par nom de champ, erreurs de lignes par
        index puis nom de champ, erreurs globales).
    """
    header_errors: dict[str, str] = {}
    line_errors: dict[int, dict[str, str]] = {}
    global_errors: list[str] = []
    if not isinstance(detail, list):
        global_errors.append(str(detail) if detail else "Données invalides.")
        return header_errors, line_errors, global_errors
    for item in detail:
        if isinstance(item, dict):
            loc = item.get("loc") or []
            msg = str(item.get("msg") or "Valeur invalide.")
        else:
            loc = []
            msg = str(item) if item else "Valeur invalide."
        if "lignes" in loc:
            rest = loc[loc.index("lignes") + 1 :]
            if len(rest) >= 2 and isinstance(rest[0], int) and rest[1] in _LINE_FIELDS:
                line_errors.setdefault(rest[0], {})[rest[1]] = msg
                continue
        elif loc and loc[-1] in _EDITABLE_HEADER_FIELDS:
            header_errors[str(loc[-1])] = msg
            continue
        context = " → ".join(str(part) for part in loc if part != "body")
        global_errors.append(f"{context} : {msg}" if context else msg)
    return header_errors, line_errors, global_errors


def _merge_posted_header(facture: Any, post: QueryDict) -> Any:
    """Réinjecte dans la facture les valeurs d'en-tête saisies.

    Utilisé pour re-rendre le formulaire après un 422 sans perdre les
    corrections de l'utilisateur. Les champs non éditables (numéro, montants,
    snapshot) gardent les valeurs de l'API.
    """
    if not isinstance(facture, dict):
        return facture
    merged = dict(facture)
    for field in _EDITABLE_HEADER_FIELDS:
        merged[field] = post.get(field, "")
    return merged


def _merge_posted_lines(
    lignes: list[Any], post: QueryDict, line_errors: dict[int, dict[str, str]]
) -> list[dict[str, Any]]:
    """Reconstruit les lignes affichées depuis les valeurs saisies.

    Chaque ligne reprend les champs édités du POST par-dessus la ligne API
    correspondante (les montants calculés restent ceux de l'API), et reçoit
    ses erreurs 422 éventuelles sous la clé `erreurs` pour affichage inline.
    La ligne API de base est retrouvée par le `ligne-N-id` posté — pas par
    l'index : après un ajout ou une suppression, les positions ne
    correspondent plus. Une ligne sans id (nouvelle) part d'une base vide.
    """
    count = _to_int(post.get("lignes_count")) or 0
    lines_by_id = {
        ligne.get("id"): ligne
        for ligne in lignes
        if isinstance(ligne, dict) and ligne.get("id") is not None
    }
    merged_lines = []
    for index in range(count):
        base = lines_by_id.get(_to_int(post.get(f"ligne-{index}-id"))) or {}
        line = dict(base)
        for field in _LINE_FIELDS:
            line[field] = post.get(f"ligne-{index}-{field}", "")
        # Id du taux en entier pour resélectionner la bonne option du select.
        tax_id = _to_int(line.get("id_taux_tva"))
        if tax_id is not None:
            line["id_taux_tva"] = tax_id
        line["erreurs"] = line_errors.get(index, {})
        merged_lines.append(line)
    return merged_lines


def _verify_recipient_sirene(request: HttpRequest, siret: Any) -> None:
    """Vérifie le SIRET destinataire dans la base SIRENE (non bloquant).

    Un SIRET introuvable ne bloque pas la validation : une entreprise récente
    ou non diffusible peut être absente de SIRENE, et le service peut être
    indisponible. On informe simplement l'utilisateur : avertissement si le
    SIRET est vide, introuvable ou invérifiable, confirmation avec la raison
    sociale s'il est trouvé.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        siret (Any): SIRET destinataire soumis par le formulaire. Obligatoire.

    Raises:
        TokenExpiredError: Session expirée (seule exception propagée).
    """
    cleaned = _normalize_siret(siret)
    if not cleaned:
        messages.warning(
            request,
            "Aucun SIRET destinataire n'est renseigné : la vérification "
            "SIRENE n'a pas pu être effectuée.",
        )
        return
    try:
        company = ClientsClient(request).search_sirene(cleaned)
    except TokenExpiredError:
        raise
    except (ResourceNotFoundError, APIValidationError):
        messages.warning(
            request,
            f"Le SIRET destinataire {cleaned} est introuvable dans la base "
            "SIRENE : vérifiez-le.",
        )
    except APIClientError:
        messages.warning(
            request,
            "La vérification SIRENE est indisponible pour le moment : le "
            "SIRET destinataire n'a pas pu être contrôlé.",
        )
    else:
        company_name = (
            company.get("raison_sociale") if isinstance(company, dict) else None
        )
        if company_name:
            messages.info(
                request,
                f"SIRET destinataire vérifié dans la base SIRENE : {company_name}.",
            )


def _handle_validate_action(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Vérifie le SIRET destinataire puis valide le brouillon.

    Appelé après un PATCH réussi : les corrections sont déjà enregistrées,
    ce que rappelle le message affiché si la validation échoue ensuite.
    La vérification SIRENE est non bloquante (simples avertissements).

    Args:
        request (HttpRequest): Requête Django courante (POST). Obligatoire.
        facture_id (int): Identifiant du brouillon à valider. Obligatoire.

    Returns:
        HttpResponse: Redirection vers la liste des factures (onglet
        validées) en cas de succès, vers le récap si la validation échoue,
        vers le login si session expirée.
    """
    saved_note = "Vos corrections ont bien été enregistrées sur le brouillon."
    try:
        _verify_recipient_sirene(request, request.POST.get("siret_destinataire"))
        facture = FacturesClient(request).validate_invoice(facture_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceConflictError as e:
        messages.error(
            request,
            str(
                e.detail
                or "La facture ne peut pas être validée (déjà validée ou "
                "brouillon incomplet)."
            ),
        )
        messages.info(request, saved_note)
        return redirect("facture_recap", facture_id=facture_id)
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        messages.info(request, saved_note)
        return redirect("facture_recap", facture_id=facture_id)
    except APIClientError as e:
        messages.error(request, str(e.message))
        messages.info(request, saved_note)
        return redirect("facture_recap", facture_id=facture_id)

    numero = facture.get("numero_facture") if isinstance(facture, dict) else None
    if numero:
        messages.success(request, f"Facture {numero} validée.")
    else:
        messages.success(request, "Facture validée.")
    # Conclusion du flux human-in-the-loop : l'utilisateur voit immédiatement
    # sa facture définitive mise en forme.
    return redirect("facture_apercu", facture_id=facture_id)


def _sirene_session_key(facture_id: int) -> str:
    """Clé de session du résultat SIRENE en attente, scopée par facture.

    Deux brouillons ouverts en parallèle ne partagent jamais leur résultat ;
    la clé est consommée (pop) au rendu suivant du récap concerné.
    """
    return f"sirene_result_{facture_id}"


def _format_client_validation_errors(detail: Any) -> str:
    """Résume le détail 422 de la création client en un message global.

    La fenêtre SIRENE n'est pas re-rendue avec des erreurs inline (choix
    MVP) : les messages de l'API sont concaténés en une seule alerte.
    """
    if isinstance(detail, list):
        parts = [
            str(item.get("msg") or item) if isinstance(item, dict) else str(item)
            for item in detail
        ]
        summary = " ; ".join(part for part in parts if part)
    else:
        summary = str(detail or "")
    return "Création du client refusée : " + (summary or "données invalides.")


def _handle_sirene_lookup_action(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Recherche SIRENE du SIRET destinataire, après enregistrement du brouillon.

    Appelée une fois le PATCH des corrections réussi : la recherche porte donc
    sur le SIRET tel qu'affiché (et désormais enregistré). Le résultat est
    déposé en session (clé scopée par facture) et consommé au rendu suivant du
    récap, qui ouvre la fenêtre de création du client. Tous les échecs sont
    non bloquants : avertissement puis retour au récap.

    Args:
        request (HttpRequest): Requête Django courante (POST). Obligatoire.
        facture_id (int): Identifiant du brouillon concerné. Obligatoire.

    Returns:
        HttpResponse: Redirection vers le récap (ou le login si session
        expirée).
    """
    siret = _normalize_siret(request.POST.get("siret_destinataire"))
    if len(siret) != 14 or not siret.isdigit():
        messages.warning(
            request,
            "Renseignez un SIRET destinataire à 14 chiffres pour lancer la "
            "recherche SIRENE.",
        )
        return redirect("facture_recap", facture_id=facture_id)
    try:
        company = ClientsClient(request).search_sirene(siret)
    except TokenExpiredError:
        return redirect("login")
    except (ResourceNotFoundError, APIValidationError):
        messages.warning(
            request,
            f"Le SIRET {siret} est introuvable dans la base SIRENE : vérifiez-le.",
        )
    except APIClientError:
        messages.warning(
            request,
            "La recherche SIRENE est indisponible pour le moment : réessayez "
            "plus tard.",
        )
    else:
        if isinstance(company, dict):
            request.session[_sirene_session_key(facture_id)] = company
        else:
            messages.warning(
                request, "La recherche SIRENE n'a renvoyé aucune donnée exploitable."
            )
    return redirect("facture_recap", facture_id=facture_id)


def _handle_create_attach_action(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Crée la fiche client depuis la fenêtre SIRENE puis la rattache au brouillon.

    POST /clients/ (schéma ClientCreate) depuis les champs `client_*` de la
    fenêtre, puis PATCH /factures/{facture_id} avec `id_client` seul — surtout
    pas le payload complet du récap : ce formulaire ne porte pas les champs de
    la facture (les corrections ont déjà été enregistrées lors de la recherche
    SIRENE). Si le rattachement échoue après la création, le client existe
    désormais dans le référentiel : au rechargement, l'encart « client
    existant » permet de relancer le rattachement seul.

    Args:
        request (HttpRequest): Requête Django courante (POST). Obligatoire.
        facture_id (int): Identifiant du brouillon concerné. Obligatoire.

    Returns:
        HttpResponse: Redirection vers le récap (ou le login si session
        expirée).
    """
    payload: dict[str, Any] = {
        "raison_sociale": str(request.POST.get("client_raison_sociale") or "").strip(),
        "code_postal": str(request.POST.get("client_code_postal") or "").strip(),
        "ville": str(request.POST.get("client_ville") or "").strip(),
    }
    if not all(payload.values()):
        messages.error(
            request,
            "Raison sociale, code postal et ville sont obligatoires pour créer "
            "le client : relancez la recherche SIRENE et complétez ces champs.",
        )
        return redirect("facture_recap", facture_id=facture_id)
    for field in ("siret", "numero_tva", "adresse"):
        value = _clean_optional(request.POST.get(f"client_{field}"))
        if value:
            payload[field] = value
    if "siret" in payload:
        payload["siret"] = payload["siret"].replace(" ", "")

    try:
        client = ClientsClient(request).create_client(payload)
    except TokenExpiredError:
        return redirect("login")
    except ResourceConflictError as e:
        messages.error(
            request,
            str(e.detail or "Un client avec ce SIRET ou ce numéro de TVA existe déjà."),
        )
        return redirect("facture_recap", facture_id=facture_id)
    except APIValidationError as e:
        messages.error(request, _format_client_validation_errors(e.detail))
        return redirect("facture_recap", facture_id=facture_id)
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("facture_recap", facture_id=facture_id)
    except APIClientError as e:
        messages.error(request, str(e.message))
        return redirect("facture_recap", facture_id=facture_id)

    client_id = client.get("id") if isinstance(client, dict) else None
    if client_id is None:
        messages.error(
            request,
            "Le client a été créé mais son identifiant n'a pas pu être lu : "
            "rechargez la page pour le rattacher.",
        )
        return redirect("facture_recap", facture_id=facture_id)

    try:
        FacturesClient(request).update_invoice(facture_id, {"id_client": client_id})
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        messages.error(
            request,
            "Le client a été créé, mais son rattachement à la facture a "
            "échoué : rechargez la page pour le rattacher.",
        )
    else:
        messages.success(request, "Client créé et rattaché à la facture.")
    return redirect("facture_recap", facture_id=facture_id)


def factures_list_view(request: HttpRequest) -> HttpResponse:
    """Affiche la liste paginée des factures, en deux onglets.

    L'onglet actif (query param `onglet` : « brouillons » par défaut, ou
    « validees ») pilote le filtre `statut` envoyé à GET /factures/. La
    recherche `q` (numéro, référence de commande ou raison sociale, déléguée
    à l'API) et les bornes `date_min`/`date_max` sur la date d'émission
    s'appliquent à l'onglet actif ; l'état complet est porté par l'URL, la
    page est donc partageable et rechargeable. La pagination réutilise
    `core.pagination` (les liens de page conservent onglet, recherche et
    filtres via `base_query`) ; les liens d'onglets conservent recherche et
    filtres mais repartent en première page (`tab_query`).

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.

    Returns:
        HttpResponse: Rendu de la liste (vide avec message d'erreur si l'API
        est indisponible), ou redirection vers le login si session expirée.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    tab = request.GET.get("onglet", _DEFAULT_TAB)
    if tab not in _TABS:
        tab = _DEFAULT_TAB
    search = request.GET.get("q", "").strip()
    date_min = request.GET.get("date_min", "").strip()
    date_max = request.GET.get("date_max", "").strip()
    page = parse_page(request.GET.get("page"))
    skip = (page - 1) * PAGE_SIZE

    items: list = []
    total = 0
    try:
        result = FacturesClient(request).list_invoices(
            search=search or None,
            statut=_TABS[tab],
            date_emission_min=date_min or None,
            date_emission_max=date_max or None,
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
            request, f"Erreur lors du chargement des factures ({e.status_code})."
        )

    pagination = build_pagination(page, total)

    # Query string des liens d'onglets : recherche et filtres conservés,
    # onglet et page retirés (chaque lien fixe son onglet et repart en
    # première page).
    tab_params = request.GET.copy()
    tab_params.pop("onglet", None)
    tab_params.pop("page", None)

    context = {
        "items": items,
        "total": total,
        "onglet": tab,
        # Valeurs courantes des filtres, pour ré-afficher l'état du formulaire.
        "search": search,
        "date_min": date_min,
        "date_max": date_max,
        "base_query": base_querystring(request),
        "tab_query": tab_params.urlencode(),
        # Query string complète, embarquée par les forms de suppression pour
        # revenir sur la liste dans le même état.
        "current_query": request.GET.urlencode(),
        **pagination,
    }
    return render(request, "core/factures.html", context)


def _safe_list_query(raw: Any) -> str:
    """Réencode une query string de retour vers la liste des factures.

    Ne conserve que les paramètres d'état connus (`_LIST_STATE_PARAMS`) : la
    valeur soumise par le formulaire n'est jamais réutilisée telle quelle
    dans la redirection.

    Args:
        raw (Any): Query string soumise (champ hidden `retour`), possiblement
            absente ou d'une autre forme. Obligatoire.

    Returns:
        str: Query string urlencodée ne contenant que les paramètres connus,
        ou chaîne vide.
    """
    parsed = QueryDict(raw if isinstance(raw, str) else "")
    params = QueryDict(mutable=True)
    for key in _LIST_STATE_PARAMS:
        value = parsed.get(key)
        if value:
            params[key] = value
    return params.urlencode()


def facture_delete_view(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Supprime un brouillon de facture depuis la liste (POST uniquement).

    Relaie DELETE /factures/{facture_id} via la couche `clients/` (pattern
    BFF : le navigateur ne touche jamais l'API). La suppression est
    définitive côté API ; la confirmation est demandée en amont par le
    formulaire de la liste. Dans tous les cas, redirige vers la liste des
    factures dans l'état transmis par le champ `retour` (onglet, recherche,
    filtres, page — réencodé en liste blanche). Un GET ne déclenche rien.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        facture_id (int): Identifiant du brouillon à supprimer. Obligatoire.

    Returns:
        HttpResponse: Redirection vers la liste des factures (avec message
        de succès ou d'erreur), ou vers le login si session expirée.
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    query = _safe_list_query(request.POST.get("retour"))
    list_url = reverse("factures") + (f"?{query}" if query else "")

    if request.method != "POST":
        return redirect(list_url)

    try:
        FacturesClient(request).delete_invoice(facture_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(
            request, "Brouillon introuvable — il a peut-être déjà été supprimé."
        )
    except ResourceConflictError as e:
        messages.error(
            request,
            str(
                e.detail
                or "Cette facture a été validée entre-temps : elle ne peut "
                "plus être supprimée."
            ),
        )
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
    except APIClientError as e:
        messages.error(request, str(e.message))
    else:
        messages.success(request, "Brouillon supprimé.")
    return redirect(list_url)


def facture_recap_view(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Affiche et traite le récapitulatif éditable d'un brouillon de facture.

    GET : charge la facture et ses lignes via GET /factures/{facture_id}
    (couche `clients/`, isolation tenant, 404 hors tenant) et pré-remplit le
    formulaire de relecture. Le référentiel des taux de TVA alimente un
    select par ligne ; s'il est injoignable, la page dégrade en affichant
    l'id du taux sans planter. Le tableau des lignes (rendu Alpine côté
    navigateur) permet d'ajouter, pré-remplir depuis le catalogue de
    produits actifs (chargé ici, sélecteur masqué si indisponible) et
    supprimer des lignes ; la dernière ligne n'est pas supprimable
    (`lignes` du contrat impose au moins un élément).

    Le rendu porte aussi l'encart « Client destinataire » (le rattachement
    est requis pour valider) : client déjà rattaché (informatif), client du
    référentiel correspondant au SIRET destinataire (bouton de rattachement),
    ou recherche SIRENE ouvrant une fenêtre de création pré-remplie.

    POST : reconstruit le payload FactureUpdate depuis la convention de
    nommage (en-tête à plat, lignes en `ligne-N-champ` + `lignes_count`) et
    enregistre les corrections via PATCH. Selon l'action soumise :
    « save » redirige vers la liste des factures, onglet brouillons (le
    message de succès s'affiche sur la liste), « validate » enchaîne
    vérification SIRENE non bloquante puis validation du brouillon,
    « attach_client » ajoute `id_client` au même PATCH (rattachement et
    corrections d'un coup), « sirene_lookup » enchaîne la recherche SIRENE
    du SIRET destinataire. « create_attach » (fenêtre SIRENE, formulaire
    séparé) court-circuite le PATCH du récap : création du client puis
    rattachement seul. Un 422 re-rend le formulaire avec les valeurs saisies
    et les erreurs rattachées aux champs ; un 409 (facture plus en brouillon)
    est signalé clairement.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        facture_id (int): Identifiant du brouillon de facture. Obligatoire.

    Returns:
        HttpResponse: Rendu du récapitulatif, ou redirection (dépôt si
        introuvable/API indisponible, login si session expirée).
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    header_errors: dict[str, str] = {}
    line_errors: dict[int, dict[str, str]] = {}
    global_errors: list[str] = []
    posted: QueryDict | None = None

    if request.method == "POST":
        action = request.POST.get("action", "save")

        # Création + rattachement depuis la fenêtre SIRENE : formulaire
        # séparé, sans les champs de la facture — ne surtout pas rejouer le
        # PATCH complet (il effacerait l'en-tête). Les corrections du récap
        # ont déjà été enregistrées lors de la recherche SIRENE.
        if action == "create_attach":
            return _handle_create_attach_action(request, facture_id)

        payload = _build_update_payload(request.POST)
        if action == "attach_client":
            client_id = _to_int(request.POST.get("client_id"))
            if client_id is None:
                messages.error(request, "Client à rattacher introuvable.")
                return redirect("facture_recap", facture_id=facture_id)
            # Rattachement et corrections en un seul PATCH.
            payload["id_client"] = client_id
        try:
            FacturesClient(request).update_invoice(facture_id, payload)
        except TokenExpiredError:
            return redirect("login")
        except ResourceNotFoundError:
            messages.error(request, "Facture introuvable.")
            return redirect("upload_document")
        except APIValidationError as e:
            # Re-rendu du formulaire avec les valeurs saisies et les erreurs
            # rattachées aux champs : on ne perd pas les corrections.
            header_errors, line_errors, global_errors = _map_validation_errors(e.detail)
            posted = request.POST
        except ResourceConflictError as e:
            messages.error(
                request,
                str(
                    e.detail
                    or "Cette facture n'est plus un brouillon : elle ne peut "
                    "plus être modifiée."
                ),
            )
            return redirect("facture_recap", facture_id=facture_id)
        except APIUnavailableError:
            messages.error(request, _MSG_INDISPONIBLE)
            return redirect("facture_recap", facture_id=facture_id)
        except APIClientError as e:
            messages.error(request, str(e.message))
            return redirect("facture_recap", facture_id=facture_id)
        else:
            if action == "validate":
                return _handle_validate_action(request, facture_id)
            if action == "attach_client":
                messages.success(request, "Client rattaché à la facture.")
                return redirect("facture_recap", facture_id=facture_id)
            if action == "sirene_lookup":
                return _handle_sirene_lookup_action(request, facture_id)
            messages.success(request, "Brouillon enregistré.")
            return redirect(reverse("factures") + "?onglet=brouillons")

    try:
        facture = FacturesClient(request).get_facture(facture_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Facture introuvable.")
        return redirect("upload_document")
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect("upload_document")
    except APIClientError as e:
        messages.error(request, str(e.message))
        return redirect("upload_document")

    # Référentiel TVA (tous les taux, y compris inactifs, pour couvrir une
    # ligne pointant un taux désactivé). Dégradation propre si indisponible :
    # liste vide, le template affiche l'id brut en champ désactivé.
    try:
        taux_tva = TauxTvaClient(request).list_taux()
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        taux_tva = []
    taux_list = taux_tva if isinstance(taux_tva, list) else []

    # Taux pré-sélectionné pour une nouvelle ligne : le premier taux actif du
    # référentiel, à défaut le premier. Sans référentiel, l'ajout de lignes
    # est désactivé côté template (impossible de choisir un taux).
    default_taux_id = next(
        (t.get("id") for t in taux_list if isinstance(t, dict) and t.get("est_actif")),
        next((t.get("id") for t in taux_list if isinstance(t, dict)), None),
    )

    # Catalogue des produits actifs, pour l'ajout de lignes pré-remplies.
    # Dégradation propre si indisponible : sélecteur masqué, page
    # fonctionnelle. Seuls les champs utiles au pré-remplissage sont
    # sérialisés vers le template.
    produits: list[dict[str, Any]] = []
    produits_partiel = False
    try:
        result_produits = ProduitsClient(request).list_products(
            est_actif=True, limit=100
        )
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        pass
    else:
        items_produits = (
            result_produits.get("items") if isinstance(result_produits, dict) else []
        )
        produits = [
            {
                "id": item.get("id"),
                "designation": str(item.get("designation") or ""),
                "reference": str(item.get("reference") or ""),
                "prix_unitaire_ht": str(item.get("prix_unitaire_ht") or ""),
                "unite": str(item.get("unite") or ""),
                "id_taux_tva": item.get("id_taux_tva"),
            }
            for item in items_produits or []
            if isinstance(item, dict) and item.get("id") is not None
        ]
        total_produits = (
            result_produits.get("total") if isinstance(result_produits, dict) else 0
        )
        produits_partiel = (_to_int(total_produits) or 0) > len(produits)

    lignes = sorted(
        facture.get("lignes") or [], key=lambda ligne: ligne.get("ordre") or 0
    )

    if posted is not None:
        facture = _merge_posted_header(facture, posted)
        lignes = _merge_posted_lines(lignes, posted, line_errors)

    # Encart « Client destinataire » : le résultat SIRENE éventuel (déposé par
    # l'action `sirene_lookup`, scopé par facture) est consommé à l'affichage
    # — pas de résidu en session, la fenêtre ne survit pas à un rechargement.
    sirene_result = request.session.pop(_sirene_session_key(facture_id), None)

    attached_client: dict | None = None
    matching_client: dict | None = None
    client_panel_error: str | None = None
    siret_destinataire = _normalize_siret(facture.get("siret_destinataire"))
    siret_destinataire_valide = (
        len(siret_destinataire) == 14 and siret_destinataire.isdigit()
    )
    if facture.get("id_client"):
        # Client déjà rattaché : encart informatif, nom en best-effort (sans
        # détail si la fiche est injoignable).
        try:
            attached_client = ClientsClient(request).get_client(facture["id_client"])
        except TokenExpiredError:
            return redirect("login")
        except APIClientError:
            attached_client = {}
    elif siret_destinataire_valide:
        # Un client du référentiel correspond-il déjà à ce SIRET ? Le param
        # `search` de GET /clients/ est flou (raison sociale, SIRET ou email) :
        # seule une égalité stricte de SIRET normalisé est retenue.
        try:
            result = ClientsClient(request).list_clients(search=siret_destinataire)
        except TokenExpiredError:
            return redirect("login")
        except APIClientError:
            client_panel_error = (
                "La recherche du client destinataire est indisponible pour le moment."
            )
        else:
            items = result.get("items") if isinstance(result, dict) else []
            matching_client = next(
                (
                    item
                    for item in items or []
                    if isinstance(item, dict)
                    and _normalize_siret(item.get("siret")) == siret_destinataire
                ),
                None,
            )

    # Alerte de divergence : le SIRET émetteur extrait par l'OCR diffère de
    # celui de l'entreprise active (posé en session au login/onboarding). Pas
    # d'alerte si l'un des deux est absent : un émetteur vide sera de toute
    # façon remplacé par celui de l'entreprise à la validation, et sans SIRET
    # entreprise en session la comparaison n'a pas de référence fiable.
    siret_emetteur = _normalize_siret(facture.get("siret_emetteur"))
    siret_entreprise = _normalize_siret(request.session.get("entreprise_siret"))
    siret_mismatch = bool(
        siret_emetteur and siret_entreprise and siret_emetteur != siret_entreprise
    )

    contexte = {
        "facture": facture,
        "lignes": lignes,
        "taux_tva": taux_list,
        "default_taux_id": default_taux_id,
        "produits": produits,
        "produits_partiel": produits_partiel,
        "snapshot_items": _snapshot_items(facture.get("snapshot_client")),
        "erreurs": header_errors,
        "erreurs_globales": global_errors,
        "siret_mismatch": siret_mismatch,
        "client_attache": attached_client,
        "client_existant": matching_client,
        "client_panel_error": client_panel_error,
        "siret_destinataire_valide": siret_destinataire_valide,
        "sirene_result": sirene_result,
    }
    return render(request, "core/facture_recap.html", contexte)


def facture_apercu_view(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Affiche l'aperçu mis en forme d'une facture (lecture seule stricte).

    Charge la facture et ses lignes via GET /factures/{facture_id} (couche
    `clients/`, isolation tenant garantie par l'API : hors périmètre = 404)
    et la présente comme une vraie facture : en-tête émetteur / « Facturé à »
    (snapshot client figé à la validation — jamais la fiche client actuelle,
    inaltérabilité oblige), tableau des prestations, totaux, pied de page
    paiement. Aucun champ éditable, aucune action de modification. Le contrat
    ne fournissant pas le libellé du statut, la page ne restreint pas aux
    factures validées : la lecture seule est le garde-fou, et la liste n'y
    pointe que depuis l'onglet validées.

    Deux appels complémentaires en best-effort (la page se dégrade sans
    planter) : l'entreprise active pour la raison sociale de l'émetteur (le
    SIRET affiché reste `siret_emetteur`, figé sur la facture) et le
    référentiel des taux de TVA pour afficher le taux de chaque ligne (le
    contrat ne porte que `id_taux_tva`).

    Cette page est le socle du futur export PDF/Factur-X : structure balisée
    comme un document, impression via un style dédié — mais aucun PDF n'est
    généré ici.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.
        facture_id (int): Identifiant de la facture à afficher. Obligatoire.

    Returns:
        HttpResponse: Rendu de l'aperçu, ou redirection (liste des factures
        validées si introuvable/API indisponible, login si session expirée).
    """
    refus = _guard_entreprise(request)
    if refus:
        return refus

    list_url = reverse("factures") + "?onglet=validees"
    try:
        facture = FacturesClient(request).get_facture(facture_id)
    except TokenExpiredError:
        return redirect("login")
    except ResourceNotFoundError:
        messages.error(request, "Facture introuvable.")
        return redirect(list_url)
    except APIUnavailableError:
        messages.error(request, _MSG_INDISPONIBLE)
        return redirect(list_url)
    except APIClientError as e:
        messages.error(request, str(e.message))
        return redirect(list_url)

    # Raison sociale de l'émetteur, en best-effort : sans elle, l'en-tête
    # affiche uniquement le SIRET émetteur figé sur la facture.
    emetteur: dict = {}
    try:
        result = EntreprisesClient(request).get_my_entreprise()
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        pass
    else:
        if isinstance(result, dict):
            emetteur = result

    # Référentiel TVA (tous les taux, y compris inactifs : une facture
    # ancienne peut pointer un taux désactivé depuis). Best-effort : taux
    # introuvable affiché « — ».
    try:
        taux_tva = TauxTvaClient(request).list_taux()
    except TokenExpiredError:
        return redirect("login")
    except APIClientError:
        taux_tva = []
    rates_by_id = {
        taux.get("id"): _format_rate(taux.get("taux"))
        for taux in (taux_tva if isinstance(taux_tva, list) else [])
        if isinstance(taux, dict)
    }

    # Lignes triées par ordre, enrichies du taux résolu (le template ne peut
    # pas indexer un dict par une clé variable).
    lignes = []
    for ligne in sorted(
        facture.get("lignes") or [], key=lambda ligne: ligne.get("ordre") or 0
    ):
        if isinstance(ligne, dict):
            ligne = dict(ligne)
            ligne["taux_tva"] = rates_by_id.get(ligne.get("id_taux_tva"))
            lignes.append(ligne)

    contexte = {
        "facture": facture,
        "lignes": lignes,
        "snapshot_items": _snapshot_items(facture.get("snapshot_client")),
        "emetteur": emetteur,
    }
    return render(request, "core/facture_apercu.html", contexte)
