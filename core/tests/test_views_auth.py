"""Tests des vues d'authentification et d'onboarding.

Parcours couverts :

- `login_view` : pose de session et redirection selon le profil (entreprise
  active, admin plateforme, aucun rattachement), échec d'identifiants, et
  dégradation quand l'API tombe pendant la résolution d'entreprise (la
  session ne doit jamais rester à moitié construite : elle est vidée) ;
- `logout_view` et la garde `_redirect_if_authenticated` des pages publiques ;
- `onboarding_view` : création du premier espace de travail (succès, 409,
  422 mappé dans les champs, API indisponible) et l'aide SIRENE — qui ne doit
  jamais bloquer la saisie manuelle, quel que soit son échec.
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.abonnements_client import AbonnementsClient
from clients.api_client import APIAuthClient
from clients.entreprises_client import EntreprisesClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from clients.clients_client import ClientsClient
from clients.utilisateurs_client import UtilisateursClient
from core.tests.conftest import ApiMocker, make_jwt, messages_of
from core.views.auth import _MSG_INDISPONIBLE, _SIRENE_SESSION_KEY

_IDENTIFIANTS = {
    "email": "user@exemple.fr",
    "password": "motdepasse",  # pragma: allowlist secret
}


class TestLoginView:
    def _mock_login_ok(self, api_mock: ApiMocker) -> None:
        api_mock(APIAuthClient, "login", returns={"access_token": make_jwt()})

    def test_succes_avec_entreprise_pose_la_session_et_va_au_dashboard(
        self, client_anonyme: Client, api_mock: ApiMocker
    ) -> None:
        self._mock_login_ok(api_mock)
        api_mock(
            AbonnementsClient,
            "get_my_subscription",
            returns=[{"id_entreprise": 42}],
        )
        api_mock(
            UtilisateursClient,
            "get_my_profile",
            returns={
                "admin_plateforme": False,
                "est_admin": True,
                "role": "PROPRIETAIRE",
            },
        )
        api_mock(
            EntreprisesClient,
            "get_my_entreprise",
            returns={"siret": "12345678900012", "raison_sociale": "ACME"},
        )

        response = client_anonyme.post(reverse("login"), _IDENTIFIANTS)

        assert response.status_code == 302
        assert response["Location"] == reverse("dashboard")
        session = client_anonyme.session
        assert session["is_authenticated"] is True
        assert session["entreprise_id"] == 42
        assert session["can_manage_team"] is True
        assert session["entreprise_nom"] == "ACME"

    def test_succes_sans_entreprise_redirige_vers_onboarding(
        self, client_anonyme: Client, api_mock: ApiMocker
    ) -> None:
        self._mock_login_ok(api_mock)
        api_mock(AbonnementsClient, "get_my_subscription", returns=[])
        api_mock(
            UtilisateursClient, "get_my_profile", returns={"admin_plateforme": False}
        )

        response = client_anonyme.post(reverse("login"), _IDENTIFIANTS)

        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")
        assert client_anonyme.session.get("entreprise_id") is None

    def test_succes_admin_plateforme_sans_entreprise_va_aux_plans(
        self, client_anonyme: Client, api_mock: ApiMocker
    ) -> None:
        self._mock_login_ok(api_mock)
        api_mock(AbonnementsClient, "get_my_subscription", returns=[])
        api_mock(
            UtilisateursClient, "get_my_profile", returns={"admin_plateforme": True}
        )

        response = client_anonyme.post(reverse("login"), _IDENTIFIANTS)

        assert response.status_code == 302
        assert response["Location"] == reverse("plans_admin")
        assert client_anonyme.session["is_platform_admin"] is True

    def test_echec_identifiants_affiche_l_erreur_sans_connecter(
        self, client_anonyme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(APIAuthClient, "login", returns={"error": "Identifiants invalides."})

        response = client_anonyme.post(reverse("login"), _IDENTIFIANTS)

        assert response.status_code == 200
        assert "Identifiants invalides." in messages_of(response)
        assert not client_anonyme.session.get("is_authenticated")

    def test_api_indisponible_pendant_la_resolution_vide_la_session(
        self, client_anonyme: Client, api_mock: ApiMocker
    ) -> None:
        """La session ne reste jamais à moitié construite (JWT sans espace)."""
        self._mock_login_ok(api_mock)
        api_mock(AbonnementsClient, "get_my_subscription", raises=APIUnavailableError())

        response = client_anonyme.post(reverse("login"), _IDENTIFIANTS)

        assert response.status_code == 200
        assert _MSG_INDISPONIBLE in messages_of(response)
        assert "is_authenticated" not in client_anonyme.session

    def test_erreur_api_pendant_la_resolution_vide_la_session(
        self, client_anonyme: Client, api_mock: ApiMocker
    ) -> None:
        self._mock_login_ok(api_mock)
        api_mock(
            AbonnementsClient,
            "get_my_subscription",
            raises=APIClientError(status_code=500),
        )

        response = client_anonyme.post(reverse("login"), _IDENTIFIANTS)

        assert response.status_code == 200
        assert "Impossible de récupérer votre espace de travail." in messages_of(
            response
        )
        assert "is_authenticated" not in client_anonyme.session


class TestLogoutView:
    def test_vide_la_session_et_redirige_vers_login(
        self, client_connecte: Client
    ) -> None:
        response = client_connecte.get(reverse("logout"))
        assert response.status_code == 302
        assert response["Location"] == reverse("login")
        assert "is_authenticated" not in client_connecte.session


class TestRedirectIfAuthenticated:
    """Un utilisateur connecté ne revoit pas les pages publiques."""

    def test_connecte_avec_entreprise_renvoye_au_dashboard(
        self, client_connecte: Client
    ) -> None:
        response = client_connecte.get(reverse("login"))
        assert response.status_code == 302
        assert response["Location"] == reverse("dashboard")

    def test_admin_plateforme_renvoye_aux_plans(
        self, client_admin_plateforme: Client
    ) -> None:
        response = client_admin_plateforme.get(reverse("login"))
        assert response.status_code == 302
        assert response["Location"] == reverse("plans_admin")

    def test_connecte_sans_entreprise_renvoye_a_l_onboarding(
        self, client_sans_entreprise: Client
    ) -> None:
        response = client_sans_entreprise.get(reverse("login"))
        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")


class TestOnboardingView:
    def test_get_sans_entreprise_affiche_le_formulaire(
        self, client_sans_entreprise: Client
    ) -> None:
        response = client_sans_entreprise.get(reverse("onboarding"))
        assert response.status_code == 200

    def test_get_avec_entreprise_redirige_vers_le_dashboard(
        self, client_connecte: Client
    ) -> None:
        response = client_connecte.get(reverse("onboarding"))
        assert response.status_code == 302
        assert response["Location"] == reverse("dashboard")

    def test_creation_pose_la_session_et_redirige(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            EntreprisesClient,
            "create_entreprise",
            returns={"id": 9, "siret": "12345678900012", "raison_sociale": "ACME"},
        )

        response = client_sans_entreprise.post(
            reverse("onboarding"), {"nom_entreprise": "ACME", "siret": ""}
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("dashboard")
        session = client_sans_entreprise.session
        assert session["entreprise_id"] == 9
        assert session["is_entreprise_admin"] is True
        assert session["can_manage_team"] is True
        assert session["entreprise_nom"] == "ACME"

    def test_conflit_409_affiche_un_message_sans_creer(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        """Le 409 n'a pas de traitement dédié ici : message générique, pas de 500."""
        api_mock(
            EntreprisesClient,
            "create_entreprise",
            raises=ResourceConflictError(detail="Ce SIRET est déjà utilisé."),
        )

        response = client_sans_entreprise.post(
            reverse("onboarding"),
            {"nom_entreprise": "ACME", "siret": "12345678900012"},
        )

        assert response.status_code == 200
        assert "Impossible de créer l'espace de travail." in messages_of(response)
        assert client_sans_entreprise.session.get("entreprise_id") is None

    def test_erreur_422_mappee_dans_les_champs(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            EntreprisesClient,
            "create_entreprise",
            raises=APIValidationError(
                detail=[{"loc": ["body", "siret"], "msg": "SIRET invalide."}]
            ),
        )

        response = client_sans_entreprise.post(
            reverse("onboarding"),
            {"nom_entreprise": "ACME", "siret": "12345678900012"},
        )

        assert response.status_code == 200
        assert response.context["form"].errors["siret"] == ["SIRET invalide."]

    def test_api_indisponible_conserve_la_saisie(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(EntreprisesClient, "create_entreprise", raises=APIUnavailableError())

        response = client_sans_entreprise.post(
            reverse("onboarding"), {"nom_entreprise": "ACME", "siret": ""}
        )

        assert response.status_code == 200
        assert _MSG_INDISPONIBLE in messages_of(response)


class TestOnboardingSirene:
    """L'aide SIRENE ne bloque jamais la saisie manuelle."""

    def _lookup(self, django_client: Client, siret: str) -> Any:
        return django_client.post(
            reverse("onboarding"),
            {"action": "sirene_lookup", "nom_entreprise": "", "siret": siret},
        )

    def test_succes_preremplit_le_formulaire_au_rendu_suivant(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        company = {"raison_sociale": "ACME", "siret": "12345678900012"}
        api_mock(ClientsClient, "search_sirene", returns=company)

        response = self._lookup(client_sans_entreprise, "12345678900012")
        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")

        # PRG : le rendu suivant consomme le résultat (pré-remplissage +
        # encart de vérification), puis la clé de session est purgée.
        suite = client_sans_entreprise.get(reverse("onboarding"))
        assert suite.context["sirene_result"] == company
        assert suite.context["form"].initial["nom_entreprise"] == "ACME"
        assert _SIRENE_SESSION_KEY not in client_sans_entreprise.session

    def test_introuvable_avertit_sans_bloquer(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ClientsClient, "search_sirene", raises=ResourceNotFoundError())

        response = self._lookup(client_sans_entreprise, "12345678900012")

        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")
        assert any(
            "introuvable dans la base SIRENE" in msg for msg in messages_of(response)
        )

    def test_api_indisponible_avertit_sans_bloquer(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ClientsClient, "search_sirene", raises=APIUnavailableError())

        response = self._lookup(client_sans_entreprise, "12345678900012")

        assert response.status_code == 302
        assert any(
            "indisponible pour le moment" in msg for msg in messages_of(response)
        )

    def test_identifiant_invalide_avertit_sans_appeler_l_api(
        self, client_sans_entreprise: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(ClientsClient, "search_sirene", returns={})

        response = self._lookup(client_sans_entreprise, "12AB")

        assert response.status_code == 302
        assert any("lancer la recherche" in msg for msg in messages_of(response))
        assert calls == []
