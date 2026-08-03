"""Tests du CRUD clients — le CRUD représentatif du projet.

La création concentre les comportements partagés par les six CRUD (clients,
catalogue, plans, taux TVA...) : succès en PRG vers la fiche, 409 SIRET
rattaché au champ par mot-clé, 422 mappé dans les champs, API indisponible
en message local sans 500. La liste vérifie la dégradation propre (page
rendue vide avec message, jamais d'erreur serveur).
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.clients_client import ClientsClient
from clients.exceptions import (
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
)
from core.tests.conftest import ApiMocker, messages_of
from core.views.auth import _MSG_INDISPONIBLE

_CREATE_URL = reverse("client_create")


def _donnees_client(**surcharge: Any) -> dict[str, Any]:
    """Données POST valides de création d'un client facturé."""
    donnees: dict[str, Any] = {
        "raison_sociale": "ACME SAS",
        "code_postal": "75001",
        "ville": "Paris",
        "siret": "12345678900012",
    }
    donnees.update(surcharge)
    return donnees


class TestClientCreation:
    def test_succes_redirige_vers_la_fiche(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(ClientsClient, "create_client", returns={"id": 7})

        response = client_connecte.post(_CREATE_URL, _donnees_client())

        assert response.status_code == 302
        assert response["Location"] == reverse("client_detail", kwargs={"client_id": 7})
        assert "Le client a été créé avec succès." in messages_of(response)
        assert calls[0][0][0]["siret"] == "12345678900012"

    def test_conflit_siret_409_rattache_au_champ(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Un client avec ce SIRET existe déjà."
        api_mock(
            ClientsClient,
            "create_client",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_connecte.post(_CREATE_URL, _donnees_client())

        assert response.status_code == 200
        assert response.context["form"].errors["siret"] == [detail]

    def test_erreur_422_mappee_dans_les_champs(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            ClientsClient,
            "create_client",
            raises=APIValidationError(
                detail=[
                    {"loc": ["body", "code_postal"], "msg": "Code postal invalide."}
                ]
            ),
        )

        response = client_connecte.post(_CREATE_URL, _donnees_client())

        assert response.status_code == 200
        assert response.context["form"].errors["code_postal"] == [
            "Code postal invalide."
        ]

    def test_api_indisponible_conserve_la_saisie(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ClientsClient, "create_client", raises=APIUnavailableError())

        response = client_connecte.post(_CREATE_URL, _donnees_client())

        assert response.status_code == 200
        assert _MSG_INDISPONIBLE in messages_of(response)


class TestClientsListe:
    def test_api_indisponible_rend_la_page_vide_avec_message(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        """Dégradation propre : la liste reste servie, jamais de 500."""
        api_mock(ClientsClient, "list_clients", raises=APIUnavailableError())

        response = client_connecte.get(reverse("clients"))

        assert response.status_code == 200
        assert response.context["items"] == []
        assert _MSG_INDISPONIBLE in messages_of(response)
