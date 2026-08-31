"""Tests du CRUD catalogue : second CRUD d'entreprise, spécificités propres.

Au-delà du pattern commun (déjà couvert en profondeur sur les clients), ce
module vérifie ce qui est propre au catalogue : le référentiel des taux de
TVA injecté dans le formulaire (et sa dégradation — formulaire affiché mais
insoumissible sans taux), la résolution du libellé de taux sur la fiche, et
les actions de (dés)activation.
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.exceptions import (
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from clients.produits_client import ProduitsClient
from clients.taux_tva_client import TauxTvaClient
from core.tests.conftest import ApiMocker, messages_of
from core.views.auth import _MSG_INDISPONIBLE

_TAUX = [{"id": 1, "taux": "20.00", "libelle": "Normal", "est_actif": True}]


def _donnees_produit(**surcharge: Any) -> dict[str, Any]:
    """Données POST valides d'un produit du catalogue."""
    donnees: dict[str, Any] = {
        "type_produit": "produit",
        "designation": "Chaise de bureau",
        "prix_unitaire_ht": "149.90",
        "id_taux_tva": "1",
    }
    donnees.update(surcharge)
    return donnees


class TestCatalogueListe:
    def test_liste_affichee(self, client_connecte: Client, api_mock: ApiMocker) -> None:
        api_mock(ProduitsClient, "list_products", returns={"items": [], "total": 0})
        response = client_connecte.get(reverse("catalogue"))
        assert response.status_code == 200

    def test_api_indisponible_rend_la_page_vide_avec_message(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ProduitsClient, "list_products", raises=APIUnavailableError())

        response = client_connecte.get(reverse("catalogue"))

        assert response.status_code == 200
        assert response.context["items"] == []
        assert _MSG_INDISPONIBLE in messages_of(response)


class TestCatalogueCreation:
    def test_succes_redirige_vers_la_fiche(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(TauxTvaClient, "list_taux", returns=list(_TAUX))
        api_mock(ProduitsClient, "create_product", returns={"id": 4})

        response = client_connecte.post(reverse("catalogue_create"), _donnees_produit())

        assert response.status_code == 302
        assert response["Location"] == reverse(
            "catalogue_detail", kwargs={"produit_id": 4}
        )
        assert "Le produit a été créé avec succès." in messages_of(response)

    def test_conflit_409_rattache_au_champ_reference(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Un produit avec cette référence existe déjà."
        api_mock(TauxTvaClient, "list_taux", returns=list(_TAUX))
        api_mock(
            ProduitsClient,
            "create_product",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_connecte.post(reverse("catalogue_create"), _donnees_produit())

        assert response.status_code == 200
        assert response.context["form"].errors["reference"] == [detail]

    def test_referentiel_tva_indisponible_bloque_la_soumission(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        """Sans taux chargés, le formulaire refuse le taux soumis — pas d'appel."""
        api_mock(TauxTvaClient, "list_taux", raises=APIUnavailableError())
        calls = api_mock(ProduitsClient, "create_product", returns={"id": 4})

        response = client_connecte.post(reverse("catalogue_create"), _donnees_produit())

        assert response.status_code == 200
        assert _MSG_INDISPONIBLE in messages_of(response)
        assert "id_taux_tva" in response.context["form"].errors
        assert calls == []


class TestCatalogueFiche:
    def test_fiche_affichee_avec_le_libelle_du_taux(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            ProduitsClient,
            "get_product",
            returns={"id": 4, "designation": "Chaise", "id_taux_tva": 1},
        )
        api_mock(TauxTvaClient, "list_taux", returns=list(_TAUX))

        response = client_connecte.get(
            reverse("catalogue_detail", kwargs={"produit_id": 4})
        )

        assert response.status_code == 200
        assert response.context["taux_label"] == "Normal — 20 %"

    def test_produit_introuvable_redirige_vers_la_liste(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ProduitsClient, "get_product", raises=ResourceNotFoundError())

        response = client_connecte.get(
            reverse("catalogue_detail", kwargs={"produit_id": 4})
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("catalogue")
        assert "Produit introuvable." in messages_of(response)


class TestCatalogueEdition:
    def test_succes_redirige_vers_la_fiche(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            ProduitsClient,
            "get_product",
            returns={"id": 4, "designation": "Chaise", "id_taux_tva": 1},
        )
        api_mock(TauxTvaClient, "list_taux", returns=list(_TAUX))
        calls = api_mock(ProduitsClient, "update_product", returns={"id": 4})

        response = client_connecte.post(
            reverse("catalogue_update", kwargs={"produit_id": 4}),
            _donnees_produit(est_actif="on"),
        )

        assert response.status_code == 302
        assert response["Location"] == reverse(
            "catalogue_detail", kwargs={"produit_id": 4}
        )
        assert "Le produit a été modifié avec succès." in messages_of(response)
        assert calls[0][0][1]["est_actif"] is True


class TestCatalogueActivation:
    def test_desactivation_puis_retour_liste(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ProduitsClient, "delete_product", returns=True)

        response = client_connecte.post(
            reverse("catalogue_deactivate", kwargs={"produit_id": 4})
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("catalogue")
        assert "Le produit a été désactivé." in messages_of(response)

    def test_desactivation_produit_introuvable(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ProduitsClient, "delete_product", raises=ResourceNotFoundError())

        response = client_connecte.post(
            reverse("catalogue_deactivate", kwargs={"produit_id": 4})
        )

        assert response.status_code == 302
        assert "Produit introuvable." in messages_of(response)

    def test_reactivation_envoie_est_actif_true(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(ProduitsClient, "update_product", returns={"id": 4})

        response = client_connecte.post(
            reverse("catalogue_reactivate", kwargs={"produit_id": 4})
        )

        assert response.status_code == 302
        assert "Le produit a été réactivé." in messages_of(response)
        assert calls[0][0] == (4, {"est_actif": True})

    def test_desactivation_refusee_422_relaye_le_detail(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Ce produit est utilisé par une facture brouillon."
        api_mock(
            ProduitsClient,
            "delete_product",
            raises=APIValidationError(detail=detail),
        )

        response = client_connecte.post(
            reverse("catalogue_deactivate", kwargs={"produit_id": 4})
        )

        assert response.status_code == 302
        assert detail in messages_of(response)
