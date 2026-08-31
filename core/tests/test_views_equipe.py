"""Tests de la page équipe : ajout, édition, statut et suppression.

Toutes les actions passent par POST sur la même vue (champ `action`) et
suivent le PRG : succès comme échec API redirigent vers la page équipe,
sauf le formulaire invalide (re-rendu avec la modale ouverte et les
erreurs). Les messages actionnables de l'API (409 limite de plan,
403 compte protégé) sont relayés à l'utilisateur.
"""

from typing import Any

from django.test import Client
from django.urls import reverse

from clients.exceptions import APIClientError, ResourceConflictError
from clients.utilisateurs_client import UtilisateursClient
from core.tests.conftest import ApiMocker, messages_of
from core.views.equipe import _MSG_COMPTE_PROTEGE

_EQUIPE_URL = reverse("equipe")

_ROLES = [{"id": 2, "libelle": "COMMERCIAL"}]


def _donnees_ajout(**surcharge: Any) -> dict[str, Any]:
    """Données POST valides d'ajout d'un collaborateur."""
    donnees: dict[str, Any] = {
        "action": "add",
        "nom": "Martin",
        "prenom": "Paul",
        "email": "paul@exemple.fr",
        "password": "temporaire1",  # pragma: allowlist secret
        "id_role": "2",
    }
    donnees.update(surcharge)
    return donnees


def _mock_liste(api_mock: ApiMocker) -> None:
    """Mocks du contexte de liste (re-rendu après échec ou GET)."""
    api_mock(UtilisateursClient, "get_roles", returns=list(_ROLES))
    api_mock(UtilisateursClient, "get_equipe", returns=[])


class TestEquipeAjout:
    def test_succes_invite_puis_redirige(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        _mock_liste(api_mock)
        calls = api_mock(UtilisateursClient, "inviter_utilisateur", returns={})

        response = client_proprietaire.post(_EQUIPE_URL, _donnees_ajout())

        assert response.status_code == 302
        assert response["Location"] == _EQUIPE_URL
        assert "L'utilisateur paul@exemple.fr a bien été ajouté." in messages_of(
            response
        )
        payload = calls[0][0][0]
        assert payload["email"] == "paul@exemple.fr"
        assert payload["id_role"] == 2

    def test_limite_du_plan_409_relaye_le_message_api(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        _mock_liste(api_mock)
        detail = "La limite de 3 utilisateurs de votre plan est atteinte."
        api_mock(
            UtilisateursClient,
            "inviter_utilisateur",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_proprietaire.post(_EQUIPE_URL, _donnees_ajout())

        assert response.status_code == 200
        assert detail in messages_of(response)

    def test_formulaire_invalide_rouvre_la_modale_sans_appeler_l_api(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        _mock_liste(api_mock)
        calls = api_mock(UtilisateursClient, "inviter_utilisateur", returns={})

        response = client_proprietaire.post(_EQUIPE_URL, _donnees_ajout(email=""))

        assert response.status_code == 200
        assert response.context["open_modal"] is True
        assert "email" in response.context["form"].errors
        assert calls == []


class TestEquipeEdition:
    def test_succes_modifie_puis_redirige(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        _mock_liste(api_mock)
        calls = api_mock(UtilisateursClient, "update_utilisateur", returns={})

        response = client_proprietaire.post(
            _EQUIPE_URL,
            _donnees_ajout(action="edit", user_id="5", password=""),
        )

        assert response.status_code == 302
        assert response["Location"] == _EQUIPE_URL
        assert "Le collaborateur a bien été modifié." in messages_of(response)
        user_id, payload = calls[0][0]
        assert user_id == "5"
        assert "password" not in payload

    def test_reactivation_refusee_409_relaye_le_message(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        detail = "La limite d'utilisateurs de votre plan est atteinte."
        api_mock(
            UtilisateursClient,
            "update_utilisateur",
            raises=ResourceConflictError(detail=detail),
        )

        response = client_proprietaire.post(
            _EQUIPE_URL, {"action": "reactivate", "user_id": "5"}
        )

        assert response.status_code == 302
        assert response["Location"] == _EQUIPE_URL
        assert detail in messages_of(response)


class TestEquipeSuppression:
    def test_succes_supprime_puis_redirige(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(UtilisateursClient, "delete_utilisateur", returns=True)

        response = client_proprietaire.post(
            _EQUIPE_URL, {"action": "delete", "user_id": "5"}
        )

        assert response.status_code == 302
        assert response["Location"] == _EQUIPE_URL
        assert "Le collaborateur a été supprimé avec succès." in messages_of(response)
        assert calls[0][0] == ("5",)

    def test_compte_protege_403_affiche_le_garde_fou(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(
            UtilisateursClient,
            "delete_utilisateur",
            raises=APIClientError(status_code=403),
        )

        response = client_proprietaire.post(
            _EQUIPE_URL, {"action": "delete", "user_id": "5"}
        )

        assert response.status_code == 302
        assert response["Location"] == _EQUIPE_URL
        assert _MSG_COMPTE_PROTEGE in messages_of(response)
