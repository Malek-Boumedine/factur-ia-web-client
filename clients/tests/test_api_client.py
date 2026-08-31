"""Tests du client d'authentification (`APIAuthClient`).

Ce client n'hérite pas de `BaseAPIClient` : la connexion précède l'obtention
du JWT. Il doit pourtant respecter la même convention IAM que le reste de la
couche cliente — c'est précisément le bug corrigé ici (un `httpx.post` nu
contournait `clients.gcp_identity`, d'où un 403 de l'ingress Cloud Run en
production). On vérifie :

- IAM activée : `X-Serverless-Authorization` part avec POST /auth/token, sans
  jamais poser d'en-tête `Authorization` (aucun JWT n'existe encore) ;
- IAM désactivée (défaut des settings de test) : ni en-tête ni la moindre
  tentative d'obtention de jeton ;
- jeton IAM inobtenable : `login` tient son contrat « jamais d'exception » et
  renvoie `{"error": ...}` sans émettre de requête HTTP.
"""

from typing import Any

import httpx
import pytest
from pytest_django.fixtures import SettingsWrapper

from clients.api_client import APIAuthClient


@pytest.fixture(autouse=True)
def cache_vierge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vide le cache module-niveau du jeton d'identité entre les tests."""
    from clients import gcp_identity

    monkeypatch.setattr(gcp_identity, "_cached_token", None)
    monkeypatch.setattr(gcp_identity, "_cached_expiry", 0.0)


@pytest.fixture
def fetch_espion(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Mock d'obtention du jeton : renvoie un jeton fixe, journalise l'appel."""
    from clients import gcp_identity

    calls: list[str] = []

    def fake_fetch(request: Any, audience: str) -> str:
        calls.append(audience)
        return "jeton-identite-google"

    monkeypatch.setattr(gcp_identity, "fetch_id_token", fake_fetch)
    return calls


@pytest.fixture
def httpx_post_mock(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Remplace `httpx.post` par un succès forgé, journalise les appels."""
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={"access_token": "jeton-jwt", "token_type": "bearer"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


class TestAuthentificationIAM:
    """IAM Cloud Run sur le chemin de connexion (aucun JWT en session)."""

    def test_active_envoie_l_identite_sans_poser_authorization(
        self,
        settings: SettingsWrapper,
        httpx_post_mock: list[dict[str, Any]],
        fetch_espion: list[str],
    ) -> None:
        settings.API_IAM_AUTH_ENABLED = True

        result = APIAuthClient().login("user@exemple.fr", "secret")

        assert result["access_token"] == "jeton-jwt"
        headers = httpx_post_mock[0]["headers"]
        assert headers["X-Serverless-Authorization"] == "Bearer jeton-identite-google"
        # Pas de JWT à ce stade : `Authorization` ne doit jamais partir.
        assert "Authorization" not in headers

    def test_desactive_n_envoie_pas_l_en_tete_et_ne_tente_rien(
        self, httpx_post_mock: list[dict[str, Any]], fetch_espion: list[str]
    ) -> None:
        # Défaut des settings de test : API_IAM_AUTH_ENABLED = False.
        result = APIAuthClient().login("user@exemple.fr", "secret")

        assert result["access_token"] == "jeton-jwt"
        assert "X-Serverless-Authorization" not in httpx_post_mock[0]["headers"]
        # Aucune tentative d'obtention de jeton.
        assert fetch_espion == []

    def test_jeton_inobtenable_renvoie_une_erreur_sans_appel_http(
        self,
        settings: SettingsWrapper,
        monkeypatch: pytest.MonkeyPatch,
        httpx_post_mock: list[dict[str, Any]],
    ) -> None:
        """Contrat de `login` : jamais d'exception, toujours un dictionnaire."""
        from clients import gcp_identity

        settings.API_IAM_AUTH_ENABLED = True

        def fetch_en_echec(request: Any, audience: str) -> str:
            raise RuntimeError("serveur de métadonnées injoignable")

        monkeypatch.setattr(gcp_identity, "fetch_id_token", fetch_en_echec)

        result = APIAuthClient().login("user@exemple.fr", "secret")

        assert result == {
            "error": "Impossible de contacter le serveur d'authentification"
        }
        assert httpx_post_mock == []


class TestContratDeLaRequete:
    """La requête de connexion reste conforme au contrat OAuth2 password."""

    def test_identifiants_en_corps_de_formulaire(
        self, httpx_post_mock: list[dict[str, Any]]
    ) -> None:
        APIAuthClient().login("user@exemple.fr", "secret")

        appel = httpx_post_mock[0]
        assert appel["url"].endswith("/auth/token")
        # Flux OAuth2 password : l'email part dans le champ `username`.
        assert appel["data"] == {
            "username": "user@exemple.fr",
            "password": "secret",  # pragma: allowlist secret
        }
