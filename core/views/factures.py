"""Vues du domaine factures.

Récapitulatif human-in-the-loop d'un brouillon de facture : affiche les
données extraites par l'OCR dans un formulaire éditable, pour relecture et
correction avant validation. Le traitement de la soumission (enregistrement
des corrections + vérification SIREN) arrive dans la tâche suivante : le POST
est pour l'instant un no-op qui affiche un message d'information.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
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


def facture_recap_view(request: HttpRequest, facture_id: int) -> HttpResponse:
    """Affiche le récapitulatif éditable d'un brouillon de facture.

    Charge la facture et ses lignes via GET /factures/{facture_id} (couche
    `clients/`, isolation tenant par le header entreprise, 404 hors tenant)
    et pré-remplit un formulaire de relecture : en-tête (numéro, dates,
    SIRET), lignes ordonnées, paiement et notes. Les montants calculés par
    l'API (lignes et totaux) sont en lecture seule. Le référentiel des taux
    de TVA alimente un select par ligne ; s'il est injoignable, la page
    dégrade en affichant l'id du taux sans planter.

    Le POST est un no-op temporaire (message d'information) : le traitement
    des corrections est branché par la tâche suivante, sans toucher au
    template (en-tête à plat aux clés du contrat, lignes en `ligne-N-champ`
    avec hidden `ligne-N-id` et `lignes_count`).

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

    if request.method == "POST":
        # Placeholder de la tâche « correction/validation » : aucune donnée
        # n'est traitée pour l'instant.
        messages.info(
            request,
            "L'enregistrement des corrections arrive dans une prochaine version.",
        )
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

    contexte = {
        "facture": facture,
        "lignes": lignes,
        "taux_tva": taux_tva if isinstance(taux_tva, list) else [],
        "snapshot_items": _snapshot_items(facture.get("snapshot_client")),
    }
    return render(request, "core/facture_recap.html", contexte)
