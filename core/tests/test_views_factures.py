"""Tests du parcours de facturation : récap, validation, transmission.

Trois volets :

- le récapitulatif (`facture_recap_view`) : affichage, dégradation propre
  (introuvable ou API indisponible → redirection avec message, jamais de
  500), enregistrement des corrections (PRG) et refus 409 quand la facture
  n'est plus un brouillon ;
- la validation (action `validate` du récap) : succès vers l'aperçu, refus
  409 avec le rappel que les corrections restent enregistrées ;
- la transmission Chorus Pro, la chaîne d'erreur la plus riche du projet :
  succès avec numéro de flux, refus métier 409 (detail relayé tel quel ou
  message de repli), 502 avec le libellé Chorus Pro relayé, 503 intégration
  non configurée, API injoignable. Toutes les issues redirigent vers
  l'aperçu (PRG).
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.exceptions import (
    APIUnavailableError,
    ResourceConflictError,
    ResourceNotFoundError,
    ServerError,
)
from clients.factures_client import FacturesClient
from clients.produits_client import ProduitsClient
from clients.taux_tva_client import TauxTvaClient
from core.tests.conftest import ApiMocker, messages_of
from core.views.auth import _MSG_INDISPONIBLE

_RECAP_URL = reverse("facture_recap", kwargs={"facture_id": 1})
_APERCU_URL = reverse("facture_apercu", kwargs={"facture_id": 1})
_TRANSMETTRE_URL = reverse("facture_transmettre_choruspro", kwargs={"facture_id": 1})

_FACTURE = {
    "id": 1,
    "numero_facture": "FA-2026-001",
    "libelle_statut": "brouillon",
    "siret_destinataire": "12345678900012",
    "lignes": [],
}


def _mock_recap_get(api_mock: ApiMocker) -> None:
    """Mocks minimaux pour rendre le récapitulatif en GET."""
    api_mock(FacturesClient, "get_facture", returns=dict(_FACTURE))
    api_mock(
        TauxTvaClient,
        "list_taux",
        returns=[{"id": 1, "taux": "20.00", "libelle": "Normal", "est_actif": True}],
    )
    api_mock(ProduitsClient, "list_products", returns={"items": [], "total": 0})


class TestFactureRecap:
    def test_get_affiche_le_recap(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        _mock_recap_get(api_mock)
        response = client_connecte.get(_RECAP_URL)
        assert response.status_code == 200

    def test_get_introuvable_redirige_vers_le_depot(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "get_facture", raises=ResourceNotFoundError())

        response = client_connecte.get(_RECAP_URL)

        assert response.status_code == 302
        assert response["Location"] == reverse("upload_document")
        assert "Facture introuvable." in messages_of(response)

    def test_get_api_indisponible_redirige_avec_message(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "get_facture", raises=APIUnavailableError())

        response = client_connecte.get(_RECAP_URL)

        assert response.status_code == 302
        assert response["Location"] == reverse("upload_document")
        assert _MSG_INDISPONIBLE in messages_of(response)

    def test_post_save_enregistre_puis_redirige_vers_les_brouillons(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(FacturesClient, "update_invoice", returns=dict(_FACTURE))

        response = client_connecte.post(_RECAP_URL, {"action": "save"})

        assert response.status_code == 302
        assert response["Location"] == reverse("factures") + "?onglet=brouillons"
        assert "Brouillon enregistré." in messages_of(response)
        assert len(calls) == 1

    def test_post_sur_facture_plus_en_brouillon_signale_le_conflit(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            FacturesClient,
            "update_invoice",
            raises=ResourceConflictError(detail="Cette facture est déjà validée."),
        )

        response = client_connecte.post(_RECAP_URL, {"action": "save"})

        assert response.status_code == 302
        assert response["Location"] == _RECAP_URL
        assert "Cette facture est déjà validée." in messages_of(response)

    def test_post_api_indisponible_redirige_sans_500(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "update_invoice", raises=APIUnavailableError())

        response = client_connecte.post(_RECAP_URL, {"action": "save"})

        assert response.status_code == 302
        assert response["Location"] == _RECAP_URL
        assert _MSG_INDISPONIBLE in messages_of(response)


class TestFactureValidation:
    """Action `validate` : PATCH des corrections puis validation du brouillon."""

    def test_succes_redirige_vers_l_apercu_avec_le_numero(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "update_invoice", returns=dict(_FACTURE))
        api_mock(
            FacturesClient,
            "validate_invoice",
            returns={"numero_facture": "FA-2026-001"},
        )

        response = client_connecte.post(_RECAP_URL, {"action": "validate"})

        assert response.status_code == 302
        assert response["Location"] == _APERCU_URL
        assert "Facture FA-2026-001 validée." in messages_of(response)

    def test_refus_409_rappelle_que_les_corrections_sont_enregistrees(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "update_invoice", returns=dict(_FACTURE))
        api_mock(
            FacturesClient,
            "validate_invoice",
            raises=ResourceConflictError(detail="Le brouillon est incomplet."),
        )

        response = client_connecte.post(_RECAP_URL, {"action": "validate"})

        assert response.status_code == 302
        assert response["Location"] == _RECAP_URL
        msgs = messages_of(response)
        assert "Le brouillon est incomplet." in msgs
        assert "Vos corrections ont bien été enregistrées sur le brouillon." in msgs


class TestTransmissionChorusPro:
    """Tous les retours de POST /factures/{id}/transmettre-choruspro."""

    def _transmettre(self, django_client: Client) -> Any:
        return django_client.post(_TRANSMETTRE_URL)

    def test_succes_affiche_le_numero_de_flux(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            FacturesClient,
            "transmit_to_choruspro",
            returns={"numero_flux_depot": "FLX-123", "date_depot": "2026-08-01"},
        )

        response = self._transmettre(client_connecte)

        assert response.status_code == 302
        assert response["Location"] == _APERCU_URL
        assert any(
            "Facture transmise à Chorus Pro" in msg and "FLX-123" in msg
            for msg in messages_of(response)
        )

    def test_refus_409_relaye_le_detail_tel_quel(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Cette facture a déjà été transmise à Chorus Pro."
        api_mock(
            FacturesClient,
            "transmit_to_choruspro",
            raises=ResourceConflictError(detail=detail),
        )

        response = self._transmettre(client_connecte)

        assert response.status_code == 302
        assert response["Location"] == _APERCU_URL
        assert detail in messages_of(response)

    def test_refus_409_sans_detail_affiche_le_message_de_repli(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            FacturesClient,
            "transmit_to_choruspro",
            raises=ResourceConflictError(detail=None),
        )

        response = self._transmettre(client_connecte)

        assert response.status_code == 302
        assert (
            "Transmission refusée : la facture ne peut pas être transmise "
            "en l'état." in messages_of(response)
        )

    def test_refus_502_relaye_le_libelle_chorus_pro(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Le SIRET destinataire est inconnu de Chorus Pro."
        api_mock(
            FacturesClient,
            "transmit_to_choruspro",
            raises=ServerError(status_code=502, detail=detail),
        )

        response = self._transmettre(client_connecte)

        assert response.status_code == 302
        assert response["Location"] == _APERCU_URL
        assert any(
            f"Dépôt refusé par Chorus Pro : {detail}" in msg
            and "vous pouvez réessayer" in msg
            for msg in messages_of(response)
        )

    def test_refus_502_sans_detail_affiche_le_message_de_repli(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            FacturesClient,
            "transmit_to_choruspro",
            raises=ServerError(status_code=502, detail=None),
        )

        response = self._transmettre(client_connecte)

        assert response.status_code == 302
        assert any(
            "Le dépôt a échoué côté Chorus Pro." in msg for msg in messages_of(response)
        )

    def test_integration_non_configuree_503(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            FacturesClient,
            "transmit_to_choruspro",
            raises=ServerError(status_code=503),
        )

        response = self._transmettre(client_connecte)

        assert response.status_code == 302
        assert "L'intégration Chorus Pro n'est pas configurée." in messages_of(response)

    def test_api_injoignable_redirige_avec_message(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "transmit_to_choruspro", raises=APIUnavailableError())

        response = self._transmettre(client_connecte)

        assert response.status_code == 302
        assert response["Location"] == _APERCU_URL
        assert _MSG_INDISPONIBLE in messages_of(response)
