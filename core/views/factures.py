"""Vues du domaine factures.

Récapitulatif human-in-the-loop d'un brouillon de facture : affiche les
données extraites par l'OCR dans un formulaire éditable, pour relecture et
correction avant validation. La soumission enregistre les corrections via
PATCH /factures/{facture_id} (en-tête + remplacement complet des lignes),
puis, selon l'action choisie, valide le brouillon avec une vérification
SIRENE non bloquante du SIRET destinataire.
"""

from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect, render

from clients.clients_client import ClientsClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from clients.factures_client import FacturesClient
from clients.taux_tva_client import TauxTvaClient
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
    "mode_paiement",
    "iban",
    "reference_commande",
    "notes",
)

# Champs éditables d'une ligne (préfixés `ligne-N-` dans le formulaire),
# alignés sur le schéma FactureLigneCreate.
_LINE_FIELDS = ("designation", "quantite", "unite", "prix_unitaire_ht", "id_taux_tva")


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
    corrections de l'utilisateur. Les champs non éditables (numéro, SIRET,
    montants, snapshot) gardent les valeurs de l'API.
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
    """
    count = _to_int(post.get("lignes_count")) or 0
    merged_lines = []
    for index in range(count):
        base = (
            lignes[index]
            if index < len(lignes) and isinstance(lignes[index], dict)
            else {}
        )
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
    cleaned = str(siret or "").strip().replace(" ", "")
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
        HttpResponse: Redirection vers le dépôt en cas de succès, vers le
        récap si la validation échoue, vers le login si session expirée.
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
    # TODO: rediriger vers l'aperçu de la facture mise en forme quand la vue
    # existera (tâche suivante) ; le dépôt sert de destination provisoire.
    return redirect("upload_document")


def facture_recap_view(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Affiche et traite le récapitulatif éditable d'un brouillon de facture.

    GET : charge la facture et ses lignes via GET /factures/{facture_id}
    (couche `clients/`, isolation tenant, 404 hors tenant) et pré-remplit le
    formulaire de relecture. Le référentiel des taux de TVA alimente un
    select par ligne ; s'il est injoignable, la page dégrade en affichant
    l'id du taux sans planter.

    POST : reconstruit le payload FactureUpdate depuis la convention de
    nommage (en-tête à plat, lignes en `ligne-N-champ` + `lignes_count`) et
    enregistre les corrections via PATCH. Selon l'action soumise :
    « save » reste sur le récap (message de succès), « validate » enchaîne
    vérification SIRENE non bloquante puis validation du brouillon. Un 422
    re-rend le formulaire avec les valeurs saisies et les erreurs rattachées
    aux champs ; un 409 (facture plus en brouillon) est signalé clairement.

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
        payload = _build_update_payload(request.POST)
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
            if request.POST.get("action") == "validate":
                return _handle_validate_action(request, facture_id)
            messages.success(request, "Brouillon enregistré.")
            return redirect("facture_recap", facture_id=facture_id)

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

    lignes = sorted(
        facture.get("lignes") or [], key=lambda ligne: ligne.get("ordre") or 0
    )

    if posted is not None:
        facture = _merge_posted_header(facture, posted)
        lignes = _merge_posted_lines(lignes, posted, line_errors)

    contexte = {
        "facture": facture,
        "lignes": lignes,
        "taux_tva": taux_tva if isinstance(taux_tva, list) else [],
        "snapshot_items": _snapshot_items(facture.get("snapshot_client")),
        "erreurs": header_errors,
        "erreurs_globales": global_errors,
    }
    return render(request, "core/facture_recap.html", contexte)
