"""Tests du domaine abonnements : mon abonnement, actions, gestion des plans.

Trois volets :

- « Mon abonnement » : résolution de la souscription active de l'entreprise
  (plan courant mis en avant, autres plans proposés au changement) et
  dégradation propre si la liste des plans est indisponible ;
- changement et prolongation : réservés aux admins de l'entreprise (flag
  `is_entreprise_admin` en garde-fou UI), messages métier des 409 relayés
  tels quels (déjà sur ce plan, plan gratuit sans échéance...) ;
- gestion des plans (admin plateforme) : CRUD avec le 409 de suppression
  (plan encore souscrit) relayé tel quel.
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.abonnements_client import AbonnementsClient
from clients.exceptions import APIUnavailableError, ResourceConflictError
from core.tests.conftest import ApiMocker, messages_of
from core.views.abonnements import _MSG_RESERVE_ADMIN_ENTREPRISE
from core.views.auth import _MSG_INDISPONIBLE

_PLANS = [
    {"id": 1, "libelle": "Gratuit", "tarif": "0.00"},
    {"id": 2, "libelle": "Pro", "tarif": "29.90"},
]

_SOUSCRIPTION_ACTIVE = {
    "id_entreprise": 1,
    "id_abonnement": 1,
    "statut": "actif",
    "date_debut": "2026-01-01",
    "date_fin": "2026-12-31",
}


def _donnees_plan(**surcharge: Any) -> dict[str, Any]:
    """Données POST valides d'un plan d'abonnement."""
    donnees: dict[str, Any] = {
        "libelle": "Pro",
        "tarif": "29.90",
        "nombre_max_utilisateurs": "5",
        "nombre_max_factures_mois": "100",
    }
    donnees.update(surcharge)
    return donnees


class TestMonAbonnement:
    def test_plan_courant_mis_en_avant_et_autres_proposes(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "list_subscriptions", returns=list(_PLANS))
        api_mock(
            AbonnementsClient,
            "get_my_subscription",
            returns=[dict(_SOUSCRIPTION_ACTIVE)],
        )

        response = client_connecte.get(reverse("abonnements"))

        assert response.status_code == 200
        assert response.context["plan_actuel"]["id"] == 1
        assert [p["id"] for p in response.context["autres_plans"]] == [2]

    def test_liste_des_plans_indisponible_page_rendue_avec_message(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "list_subscriptions", raises=APIUnavailableError())
        api_mock(AbonnementsClient, "get_my_subscription", returns=[])

        response = client_connecte.get(reverse("abonnements"))

        assert response.status_code == 200
        assert _MSG_INDISPONIBLE in messages_of(response)


class TestChangementDePlan:
    def test_non_admin_entreprise_refuse_sans_appel_api(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(AbonnementsClient, "change_plan", returns={})

        response = client_connecte.post(
            reverse("abonnement_changer", kwargs={"abonnement_id": 2})
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("abonnements")
        assert _MSG_RESERVE_ADMIN_ENTREPRISE in messages_of(response)
        assert calls == []

    def test_admin_entreprise_change_de_plan(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(AbonnementsClient, "change_plan", returns={})

        response = client_proprietaire.post(
            reverse("abonnement_changer", kwargs={"abonnement_id": 2})
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("abonnements")
        assert "Votre abonnement a été mis à jour avec succès." in messages_of(response)
        assert calls[0][0] == (2,)

    def test_conflit_409_relaye_le_message_metier(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Votre entreprise est déjà sur ce plan."
        api_mock(
            AbonnementsClient,
            "change_plan",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_proprietaire.post(
            reverse("abonnement_changer", kwargs={"abonnement_id": 2})
        )

        assert response.status_code == 302
        assert detail in messages_of(response)


class TestProlongation:
    def test_succes_affiche_la_nouvelle_echeance(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "extend_plan", returns={"date_fin": "2026-09-30"})

        response = client_proprietaire.post(reverse("abonnement_prolonger"))

        assert response.status_code == 302
        assert any("30/09/2026" in msg for msg in messages_of(response))

    def test_plan_gratuit_409_relaye_le_message(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Le plan gratuit n'a pas d'échéance à prolonger."
        api_mock(
            AbonnementsClient,
            "extend_plan",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_proprietaire.post(reverse("abonnement_prolonger"))

        assert response.status_code == 302
        assert detail in messages_of(response)

    def test_non_admin_entreprise_refuse(self, client_connecte: Client) -> None:
        response = client_connecte.post(reverse("abonnement_prolonger"))
        assert response.status_code == 302
        assert _MSG_RESERVE_ADMIN_ENTREPRISE in messages_of(response)


class TestGestionDesPlans:
    def test_creation_retourne_a_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "create_subscription", returns={"id": 3})

        response = client_admin_plateforme.post(reverse("plan_create"), _donnees_plan())

        assert response.status_code == 302
        assert response["Location"] == reverse("plans_admin")
        assert "Le plan a été créé avec succès." in messages_of(response)

    def test_creation_conflit_409_rattache_au_libelle(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Un plan avec ce libellé existe déjà."
        api_mock(
            AbonnementsClient,
            "create_subscription",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_admin_plateforme.post(reverse("plan_create"), _donnees_plan())

        assert response.status_code == 200
        assert response.context["form"].errors["libelle"] == [detail]

    def test_edition_retrouve_le_plan_dans_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "list_subscriptions", returns=list(_PLANS))
        calls = api_mock(AbonnementsClient, "update_subscription", returns={})

        response = client_admin_plateforme.post(
            reverse("plan_update", kwargs={"abonnement_id": 2}),
            _donnees_plan(libelle="Pro Plus"),
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("plans_admin")
        assert "Le plan a été modifié avec succès." in messages_of(response)
        assert calls[0][0][1]["libelle"] == "Pro Plus"

    def test_edition_plan_absent_de_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "list_subscriptions", returns=list(_PLANS))

        response = client_admin_plateforme.get(
            reverse("plan_update", kwargs={"abonnement_id": 99})
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("plans_admin")
        assert "Plan introuvable." in messages_of(response)

    def test_suppression_retourne_a_la_liste(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "delete_subscription", returns=True)

        response = client_admin_plateforme.post(
            reverse("plan_delete", kwargs={"abonnement_id": 3})
        )

        assert response.status_code == 302
        assert "Le plan a été supprimé." in messages_of(response)

    def test_suppression_plan_souscrit_409_relaye_le_message(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Ce plan est encore souscrit par 2 entreprises."
        api_mock(
            AbonnementsClient,
            "delete_subscription",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_admin_plateforme.post(
            reverse("plan_delete", kwargs={"abonnement_id": 3})
        )

        assert response.status_code == 302
        assert detail in messages_of(response)
