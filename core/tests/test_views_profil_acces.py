"""Tests des pages compte : « Informations » (profil) et « Mes accès ».

Le profil couvre l'affichage best-effort (la page reste utilisable si l'API
échoue) et la mise à jour PRG. La page accès couvre les deux opérations
sensibles, chacune avec ses spécificités :

- changement d'email : le nouvel email est le sujet du JWT — la réponse
  porte un token neuf qui REMPLACE `jwt_token` en session ; sans token dans
  la réponse (hors contrat), la session est vidée par sécurité ;
- changement de mot de passe ; dans les deux cas, les 400 (mot de passe
  actuel incorrect) affichent un message volontairement ambigu — rien ne
  doit permettre de sonder un mot de passe ou l'existence d'un email.
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.entreprises_client import EntreprisesClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
)
from clients.utilisateurs_client import UtilisateursClient
from core.tests.conftest import ApiMocker, messages_of
from core.views.acces import _MSG_400_EMAIL, _MSG_400_MDP

_PROFIL = {
    "email": "user@exemple.fr",
    "nom": "Durand",
    "prenom": "Alice",
    "role": "PROPRIETAIRE",
    "est_admin": True,
}


def _donnees_email(**surcharge: Any) -> dict[str, Any]:
    """Données POST valides du changement d'email."""
    donnees: dict[str, Any] = {
        "action": "email",
        "mot_de_passe_actuel": "actuel-mdp",  # pragma: allowlist secret
        "nouvel_email": "nouveau@exemple.fr",
    }
    donnees.update(surcharge)
    return donnees


def _donnees_mdp() -> dict[str, Any]:
    """Données POST valides du changement de mot de passe."""
    return {
        "action": "mot_de_passe",
        "mot_de_passe_actuel": "actuel-mdp",  # pragma: allowlist secret
        "nouveau_mot_de_passe": "nouveau-mdp1",  # pragma: allowlist secret
        "confirm_password": "nouveau-mdp1",  # pragma: allowlist secret
    }


class TestProfil:
    def test_affichage_avec_entreprise(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(
            EntreprisesClient,
            "get_my_entreprise",
            returns={"raison_sociale": "ACME"},
        )

        response = client_connecte.get(reverse("profil"))

        assert response.status_code == 200
        assert response.context["role"] == "PROPRIETAIRE"
        assert response.context["entreprise"] == {"raison_sociale": "ACME"}

    def test_api_en_echec_la_page_reste_utilisable(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_my_profile", raises=APIUnavailableError())
        api_mock(
            EntreprisesClient,
            "get_my_entreprise",
            raises=APIClientError(status_code=500),
        )

        response = client_connecte.get(reverse("profil"))

        assert response.status_code == 200
        assert response.context["entreprise_error"] is not None

    def test_mise_a_jour_succes_en_prg(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(
            EntreprisesClient,
            "get_my_entreprise",
            returns={"raison_sociale": "ACME"},
        )
        calls = api_mock(UtilisateursClient, "update_my_profile", returns={})

        response = client_connecte.post(
            reverse("profil"),
            {"nom": "Durand", "prenom": "Alice", "ville": "Lyon"},
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("profil")
        assert "Vos informations ont été mises à jour." in messages_of(response)
        assert calls[0][0][0]["ville"] == "Lyon"

    def test_erreur_422_mappee_dans_les_champs(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(
            EntreprisesClient,
            "get_my_entreprise",
            returns={"raison_sociale": "ACME"},
        )
        api_mock(
            UtilisateursClient,
            "update_my_profile",
            raises=APIValidationError(
                detail=[{"loc": ["body", "telephone"], "msg": "Numéro invalide."}]
            ),
        )

        response = client_connecte.post(
            reverse("profil"), {"nom": "Durand", "prenom": "Alice"}
        )

        assert response.status_code == 200
        assert response.context["form_infos"].errors["telephone"] == [
            "Numéro invalide."
        ]


class TestChangementEmail:
    def test_succes_remplace_le_jwt_en_session(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(
            UtilisateursClient,
            "change_my_email",
            returns={"access_token": "jeton-neuf"},
        )

        response = client_connecte.post(reverse("acces"), _donnees_email())

        assert response.status_code == 302
        assert response["Location"] == reverse("acces")
        assert "Votre email a été modifié." in messages_of(response)
        session = client_connecte.session
        assert session["jwt_token"] == "jeton-neuf"
        assert session["user_email"] == "nouveau@exemple.fr"

    def test_reponse_sans_token_vide_la_session_par_securite(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        """Hors contrat : sans token neuf, la session ne peut plus appeler l'API."""
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(UtilisateursClient, "change_my_email", returns={})

        response = client_connecte.post(reverse("acces"), _donnees_email())

        assert response.status_code == 302
        assert response["Location"] == reverse("login")
        assert "is_authenticated" not in client_connecte.session

    def test_email_deja_utilise_409_rattache_au_champ(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        detail = "Cet email est déjà utilisé par un autre compte."
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(
            UtilisateursClient,
            "change_my_email",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_connecte.post(reverse("acces"), _donnees_email())

        assert response.status_code == 200
        assert response.context["form_email"].errors["nouvel_email"] == [detail]

    def test_mot_de_passe_incorrect_400_message_ambigu(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(
            UtilisateursClient,
            "change_my_email",
            raises=APIClientError(status_code=400),
        )

        response = client_connecte.post(reverse("acces"), _donnees_email())

        assert response.status_code == 200
        assert response.context["form_email"].errors["mot_de_passe_actuel"] == [
            _MSG_400_EMAIL
        ]


class TestChangementMotDePasse:
    def test_succes_en_prg(self, client_connecte: Client, api_mock: ApiMocker) -> None:
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(UtilisateursClient, "change_my_password", returns=True)

        response = client_connecte.post(reverse("acces"), _donnees_mdp())

        assert response.status_code == 302
        assert response["Location"] == reverse("acces")
        assert "Votre mot de passe a été modifié." in messages_of(response)

    def test_mot_de_passe_incorrect_400_message_ambigu(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_my_profile", returns=dict(_PROFIL))
        api_mock(
            UtilisateursClient,
            "change_my_password",
            raises=APIClientError(status_code=400),
        )

        response = client_connecte.post(reverse("acces"), _donnees_mdp())

        assert response.status_code == 200
        assert response.context["form_mdp"].errors["mot_de_passe_actuel"] == [
            _MSG_400_MDP
        ]
