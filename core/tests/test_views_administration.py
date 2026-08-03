"""Tests du backoffice plateforme : entreprises et admins.

Deux écrans réservés aux administrateurs de plateforme :

- gestion des entreprises : liste, fiche (avec le pré-affichage du blocage
  de suppression), correction d'identité légale, et les actions
  d'abonnement/suspension/suppression — dont les refus métier de l'API
  (403/409 à message explicite) sont relayés tels quels ;
- gestion des admins : liste, recherche d'utilisateurs, promotion et
  révocation.

Les retours d'action suivent le PRG : fiche (`origine=detail`) ou liste.
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.abonnements_client import AbonnementsClient
from clients.administration_client import AdministrationClient
from clients.admins_plateforme_client import AdminsPlateformeClient
from clients.exceptions import (
    APIClientError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from clients.formes_juridiques_client import FormesJuridiquesClient
from core.tests.conftest import ApiMocker, messages_of

_LISTE_URL = reverse("admin_entreprises")
_DETAIL_URL = reverse("admin_entreprise_detail", kwargs={"entreprise_id": 5})


def _entreprise(**surcharge: Any) -> dict[str, Any]:
    """Fiche entreprise minimale du schéma EntrepriseAdminDetail."""
    fiche: dict[str, Any] = {
        "id": 5,
        "nom_entreprise": "ACME SAS",
        "siret": "12345678900012",
        "membres": [],
        "souscriptions": [],
        "compteurs": {},
        "souscription": {"id_abonnement": 1},
    }
    fiche.update(surcharge)
    return fiche


class TestEntreprisesListe:
    def test_liste_affichee(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            AdministrationClient,
            "list_entreprises",
            returns={"items": [], "total": 0},
        )
        response = client_admin_plateforme.get(_LISTE_URL)
        assert response.status_code == 200


class TestEntrepriseDetail:
    def test_fiche_affichee_sans_blocage_de_suppression(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdministrationClient, "get_entreprise", returns=_entreprise())
        api_mock(AbonnementsClient, "list_subscriptions", returns=[])

        response = client_admin_plateforme.get(_DETAIL_URL)

        assert response.status_code == 200
        assert response.context["blocage_suppression"] == ""

    def test_facture_scellee_bloque_la_suppression(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        """Une facture émise impose la conservation : seul recours, suspendre."""
        api_mock(
            AdministrationClient,
            "get_entreprise",
            returns=_entreprise(
                compteurs={"factures_total": 2, "factures_scellees": 1}
            ),
        )
        api_mock(AbonnementsClient, "list_subscriptions", returns=[])

        response = client_admin_plateforme.get(_DETAIL_URL)

        blocage = response.context["blocage_suppression"]
        assert "2 factures" in blocage
        assert "obligation de conservation" in blocage

    def test_entreprise_introuvable_redirige_vers_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdministrationClient, "get_entreprise", raises=ResourceNotFoundError())

        response = client_admin_plateforme.get(_DETAIL_URL)

        assert response.status_code == 302
        assert response["Location"] == _LISTE_URL
        assert "Entreprise introuvable." in messages_of(response)


class TestEntrepriseEdition:
    def _mock_fiche(self, api_mock: ApiMocker) -> None:
        api_mock(AdministrationClient, "get_entreprise", returns=_entreprise())
        api_mock(
            FormesJuridiquesClient,
            "list_formes",
            returns=[{"id": 1, "libelle": "SAS"}],
        )

    def test_succes_redirige_vers_la_fiche(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        self._mock_fiche(api_mock)
        calls = api_mock(AdministrationClient, "update_entreprise", returns={})

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_update", kwargs={"entreprise_id": 5}),
            {"nom_entreprise": "ACME SAS", "siret": "123 456 789 00012"},
        )

        assert response.status_code == 302
        assert response["Location"] == _DETAIL_URL
        assert "L'entreprise a été modifiée avec succès." in messages_of(response)
        # Le SIRET soumis avec séparateurs part normalisé vers l'API.
        assert calls[0][0][1]["siret"] == "12345678900012"

    def test_conflit_siret_409_rattache_au_champ(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        self._mock_fiche(api_mock)
        detail = "Ce SIRET est déjà rattaché à une autre entreprise."
        api_mock(
            AdministrationClient,
            "update_entreprise",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_update", kwargs={"entreprise_id": 5}),
            {"nom_entreprise": "ACME SAS", "siret": "12345678900012"},
        )

        assert response.status_code == 200
        assert response.context["form"].errors["siret"] == [detail]


class TestEntrepriseActions:
    def test_changement_de_plan_sans_selection_refuse_sans_appel(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(AdministrationClient, "change_plan", returns={})

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_change_plan", kwargs={"entreprise_id": 5}),
            {"id_abonnement": ""},
        )

        assert response.status_code == 302
        assert response["Location"] == _DETAIL_URL
        assert "Veuillez sélectionner un plan d'abonnement." in messages_of(response)
        assert calls == []

    def test_changement_de_plan_succes(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(AdministrationClient, "change_plan", returns={})

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_change_plan", kwargs={"entreprise_id": 5}),
            {"id_abonnement": "2"},
        )

        assert response.status_code == 302
        assert "Le plan d'abonnement a été changé." in messages_of(response)
        assert calls[0][0] == (5, 2)

    def test_prolongation_succes(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdministrationClient, "extend_subscription", returns={})

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_extend", kwargs={"entreprise_id": 5})
        )

        assert response.status_code == 302
        assert "L'abonnement a été prolongé d'un mois." in messages_of(response)

    def test_suspension_depuis_la_fiche_revient_a_la_fiche(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(AdministrationClient, "suspend_entreprise", returns={})

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_suspend", kwargs={"entreprise_id": 5}),
            {"motif": "Impayés répétés", "origine": "detail"},
        )

        assert response.status_code == 302
        assert response["Location"] == _DETAIL_URL
        assert calls[0][0] == (5, "Impayés répétés")

    def test_suspension_depuis_la_liste_revient_a_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdministrationClient, "suspend_entreprise", returns={})

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_suspend", kwargs={"entreprise_id": 5}),
            {"motif": ""},
        )

        assert response.status_code == 302
        assert response["Location"] == _LISTE_URL

    def test_reactivation_revient_a_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdministrationClient, "reactivate_entreprise", returns={})

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_reactivate", kwargs={"entreprise_id": 5})
        )

        assert response.status_code == 302
        assert response["Location"] == _LISTE_URL
        assert any("réactivée" in msg for msg in messages_of(response))

    def test_suppression_succes_revient_a_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdministrationClient, "delete_entreprise", returns=True)

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_delete", kwargs={"entreprise_id": 5})
        )

        assert response.status_code == 302
        assert response["Location"] == _LISTE_URL
        assert "L'entreprise a été supprimée." in messages_of(response)

    def test_suppression_refusee_409_reste_sur_la_fiche(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        detail = "L'entreprise contient encore 3 clients."
        api_mock(
            AdministrationClient,
            "delete_entreprise",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_delete", kwargs={"entreprise_id": 5})
        )

        assert response.status_code == 302
        assert response["Location"] == _DETAIL_URL
        assert detail in messages_of(response)

    def test_suppression_403_garde_fou_metier_relaye(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Une facture émise ne peut jamais être supprimée."
        api_mock(
            AdministrationClient,
            "delete_entreprise",
            raises=APIClientError(status_code=403, detail=detail),
        )

        response = client_admin_plateforme.post(
            reverse("admin_entreprise_delete", kwargs={"entreprise_id": 5})
        )

        assert response.status_code == 302
        assert response["Location"] == _DETAIL_URL
        assert detail in messages_of(response)


class TestAdminsPlateforme:
    def test_promotion_succes(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(AdminsPlateformeClient, "promote_admin", returns={})

        response = client_admin_plateforme.post(
            reverse("admins_plateforme"),
            {"action": "promote", "utilisateur_id": "7"},
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("admins_plateforme")
        assert "L'utilisateur a été promu administrateur de plateforme." in messages_of(
            response
        )
        assert calls[0][0] == (7,)

    def test_revocation_succes(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdminsPlateformeClient, "revoke_admin", returns={})

        response = client_admin_plateforme.post(
            reverse("admins_plateforme"),
            {"action": "revoke", "utilisateur_id": "7"},
        )

        assert response.status_code == 302
        assert (
            "Les droits d'administrateur de plateforme ont été révoqués."
            in messages_of(response)
        )

    def test_action_invalide_refusee_sans_appel(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(AdminsPlateformeClient, "promote_admin", returns={})

        response = client_admin_plateforme.post(
            reverse("admins_plateforme"),
            {"action": "promote", "utilisateur_id": "pas-un-id"},
        )

        assert response.status_code == 302
        assert "Action invalide." in messages_of(response)
        assert calls == []

    def test_recherche_d_utilisateur_a_promouvoir(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdminsPlateformeClient, "list_admins", returns=[])
        resultats = [{"id": 7, "email": "paul@exemple.fr"}]
        api_mock(AdminsPlateformeClient, "search_user_by_email", returns=resultats)

        response = client_admin_plateforme.get(
            reverse("admins_plateforme"), {"email": "paul"}
        )

        assert response.status_code == 200
        assert response.context["search_results"] == resultats
