"""Tests de l'administration des taux de TVA (référentiel plateforme).

CRUD réservé aux admins plateforme. Au-delà du pattern commun, vérifie le
cas « flag de session obsolète » : la session se croit admin mais l'API
répond 403 — l'API fait autorité, l'utilisateur est renvoyé à l'accueil.
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.exceptions import (
    APIClientError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from clients.taux_tva_client import TauxTvaClient
from core.tests.conftest import ApiMocker, messages_of
from core.views.admins_plateforme import _MSG_ACCES_REFUSE


def _donnees_taux(**surcharge: Any) -> dict[str, Any]:
    """Données POST valides d'un taux de TVA."""
    donnees: dict[str, Any] = {"taux": "5.50", "libelle": "Taux réduit"}
    donnees.update(surcharge)
    return donnees


class TestTauxTvaListe:
    def test_liste_affichee(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            TauxTvaClient,
            "list_taux",
            returns=[{"id": 1, "taux": "20.00", "libelle": "Normal"}],
        )
        response = client_admin_plateforme.get(reverse("taux_tva_admin"))
        assert response.status_code == 200

    def test_flag_admin_obsolete_le_403_api_fait_autorite(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        """Session admin mais API 403 : accès refusé, retour à l'accueil."""
        api_mock(TauxTvaClient, "list_taux", raises=APIClientError(status_code=403))

        response = client_admin_plateforme.get(reverse("taux_tva_admin"))

        assert response.status_code == 302
        assert response["Location"] == reverse("home")
        assert _MSG_ACCES_REFUSE in messages_of(response)


class TestTauxTvaCreation:
    def test_succes_retourne_a_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(TauxTvaClient, "create_taux", returns={"id": 3})

        response = client_admin_plateforme.post(
            reverse("taux_tva_create"), _donnees_taux()
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("taux_tva_admin")
        assert "Le taux de TVA a été créé avec succès." in messages_of(response)

    def test_conflit_409_rattache_au_champ_taux(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Un taux avec cette valeur existe déjà."
        api_mock(
            TauxTvaClient,
            "create_taux",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_admin_plateforme.post(
            reverse("taux_tva_create"), _donnees_taux()
        )

        assert response.status_code == 200
        assert response.context["form"].errors["taux"] == [detail]


class TestTauxTvaEdition:
    def test_succes_retourne_a_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            TauxTvaClient,
            "get_taux",
            returns={"id": 3, "taux": "5.50", "libelle": "Réduit"},
        )
        calls = api_mock(TauxTvaClient, "update_taux", returns={"id": 3})

        response = client_admin_plateforme.post(
            reverse("taux_tva_update", kwargs={"taux_tva_id": 3}),
            _donnees_taux(libelle="Taux super réduit"),
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("taux_tva_admin")
        assert "Le taux de TVA a été modifié avec succès." in messages_of(response)
        assert calls[0][0][1]["libelle"] == "Taux super réduit"

    def test_taux_introuvable_redirige_vers_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(TauxTvaClient, "get_taux", raises=ResourceNotFoundError())

        response = client_admin_plateforme.get(
            reverse("taux_tva_update", kwargs={"taux_tva_id": 3})
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("taux_tva_admin")
        assert "Taux de TVA introuvable." in messages_of(response)


class TestTauxTvaActivation:
    def test_desactivation_puis_retour_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(TauxTvaClient, "deactivate_taux", returns=True)

        response = client_admin_plateforme.post(
            reverse("taux_tva_deactivate", kwargs={"taux_tva_id": 3})
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("taux_tva_admin")
        assert "Le taux de TVA a été désactivé." in messages_of(response)

    def test_desactivation_refusee_422_relaye_le_detail(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Ce taux est utilisé par des produits du catalogue."
        api_mock(
            TauxTvaClient,
            "deactivate_taux",
            raises=APIValidationError(detail=detail),
        )

        response = client_admin_plateforme.post(
            reverse("taux_tva_deactivate", kwargs={"taux_tva_id": 3})
        )

        assert response.status_code == 302
        assert detail in messages_of(response)

    def test_reactivation_envoie_est_actif_true(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(TauxTvaClient, "update_taux", returns={"id": 3})

        response = client_admin_plateforme.post(
            reverse("taux_tva_reactivate", kwargs={"taux_tva_id": 3})
        )

        assert response.status_code == 302
        assert "Le taux de TVA a été réactivé." in messages_of(response)
        assert calls[0][0] == (3, {"est_actif": True})
