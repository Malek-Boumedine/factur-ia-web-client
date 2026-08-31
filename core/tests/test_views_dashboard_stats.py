"""Tests du tableau de bord et de la page statistiques.

Deux pages en lecture seule dont l'exigence principale est la dégradation
indépendante par zone : chaque appel API qui échoue n'éteint que sa propre
zone (flag `*_disponibles` à False), la page est toujours rendue — jamais
de 500. Le nom d'entreprise du bandeau est résolu en best-effort.
"""

from datetime import date

from django.test import Client
from django.urls import reverse

from clients.entreprises_client import EntreprisesClient
from clients.exceptions import APIClientError, APIUnavailableError
from clients.factures_client import FacturesClient
from core.tests.conftest import ApiMocker


def _stats_deux_mois() -> dict[str, object]:
    """Statistiques minimales avec un CA sur le mois courant et le précédent."""
    today = date.today()
    if today.month == 1:
        previous = f"{today.year - 1}-12"
    else:
        previous = f"{today.year}-{today.month - 1:02d}"
    return {
        "par_mois": [
            {"mois": f"{today.year}-{today.month:02d}", "ca_ttc": "1200.00"},
            {"mois": previous, "ca_ttc": "1000.00"},
        ]
    }


class TestDashboard:
    def test_affichage_nominal(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "get_statistiques", returns=_stats_deux_mois())
        api_mock(FacturesClient, "list_invoices", returns={"items": []})
        api_mock(
            EntreprisesClient,
            "get_my_entreprise",
            returns={"raison_sociale": "ACME"},
        )

        response = client_connecte.get(reverse("dashboard"))

        assert response.status_code == 200
        assert response.context["stats_disponibles"] is True
        assert response.context["factures_disponibles"] is True
        assert response.context["entreprise_nom"] == "ACME"

    def test_chaque_zone_degrade_independamment(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        """Statistiques et activité récente en échec : page rendue quand même."""
        api_mock(
            FacturesClient,
            "get_statistiques",
            raises=APIClientError(status_code=500),
        )
        api_mock(
            FacturesClient,
            "list_invoices",
            raises=APIClientError(status_code=500),
        )
        api_mock(
            EntreprisesClient,
            "get_my_entreprise",
            raises=APIClientError(status_code=500),
        )

        response = client_connecte.get(reverse("dashboard"))

        assert response.status_code == 200
        assert response.context["stats_disponibles"] is False
        assert response.context["factures_disponibles"] is False
        assert response.context["entreprise_nom"] is None


class TestStatistiques:
    def test_affichage_nominal(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "get_statistiques", returns=_stats_deux_mois())

        response = client_connecte.get(reverse("statistiques"))

        assert response.status_code == 200
        assert response.context["stats_disponibles"] is True

    def test_api_indisponible_le_selecteur_reste_rendu(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(FacturesClient, "get_statistiques", raises=APIUnavailableError())

        response = client_connecte.get(reverse("statistiques"))

        assert response.status_code == 200
        assert response.context["stats_disponibles"] is False
