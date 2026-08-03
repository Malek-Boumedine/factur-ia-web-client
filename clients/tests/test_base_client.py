"""Tests du socle HTTP de la couche cliente (`BaseAPIClient`).

Seul endroit des tests où l'on descend au niveau HTTP : `httpx.request` est
remplacé par une séquence programmée de réponses forgées ou d'exceptions
réseau, pour vérifier :

- l'injection des en-têtes depuis la session Django (JWT Bearer, tenant
  `x-entreprise-id`) ;
- le mapping des statuts vers les exceptions métier, `detail` conservé là où
  les vues en dépendent (409, 422, 5xx, 403) ;
- le 401 : purge de la session AVANT la levée de `TokenExpiredError` ;
- la politique de rejeu : erreurs transitoires (502/503/504, réseau)
  rejouées sur les méthodes idempotentes uniquement — un POST n'est JAMAIS
  rejoué, et son 502 remonte en `ServerError` avec son `detail` (libellé
  métier Chorus Pro).

`get_stream` est volontairement hors périmètre (coût de test élevé pour du
relais de flux). Le backoff est neutralisé (`API_RETRY_BACKOFF = 0` dans les
settings de test) : aucun test ne dort.
"""

from importlib import import_module
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest
from django.test import RequestFactory

from clients.base_client import BaseAPIClient
from clients.exceptions import (
    APIClientError,
    APIUnavailableError,
    APIValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    ServerError,
    TokenExpiredError,
)


@pytest.fixture
def bff_request() -> HttpRequest:
    """Requête Django munie d'une session et du stockage de messages.

    `BaseAPIClient` lit la session (JWT, entreprise) et dépose un message au
    401 : les deux mécanismes doivent être présents, comme en production.
    """
    request = RequestFactory().get("/")
    engine = import_module(settings.SESSION_ENGINE)
    request.session = engine.SessionStore()
    request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
    return request


@pytest.fixture
def api_client(bff_request: HttpRequest) -> BaseAPIClient:
    """Client de base avec politique de rejeu déterministe (2 rejeux, sans attente)."""
    client = BaseAPIClient(bff_request)
    client._max_retries = 2
    client._retry_backoff = 0.0
    return client


@pytest.fixture
def httpx_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Remplace `httpx.request` par une séquence programmée d'issues.

    Chaque issue est soit une `httpx.Response` forgée (renvoyée), soit une
    exception (levée). La séquence doit couvrir exactement le nombre d'appels
    attendus : un appel de trop échoue explicitement.

    Returns:
        Fonction `(outcomes) -> journal` : installe la séquence et renvoie le
        journal des appels (méthode, URL, en-têtes réellement envoyés).
    """

    def _install(outcomes: list[Any]) -> list[dict[str, Any]]:
        remaining = list(outcomes)
        calls: list[dict[str, Any]] = []

        def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
            calls.append({"method": method, "url": url, **kwargs})
            assert remaining, "httpx.request appelé plus souvent que prévu"
            outcome = remaining.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(httpx, "request", fake_request)
        return calls

    return _install


class TestHeaders:
    """Injection des en-têtes d'authentification depuis la session."""

    def test_session_complete_injecte_jwt_et_tenant(
        self, api_client: BaseAPIClient
    ) -> None:
        api_client.request.session["jwt_token"] = "jeton-jwt"
        api_client.request.session["entreprise_id"] = 42

        headers = api_client.headers

        assert headers["Authorization"] == "Bearer jeton-jwt"
        assert headers["x-entreprise-id"] == "42"
        assert headers["Content-Type"] == "application/json"

    def test_session_vide_omet_les_en_tetes_optionnels(
        self, api_client: BaseAPIClient
    ) -> None:
        headers = api_client.headers
        assert "Authorization" not in headers
        assert "x-entreprise-id" not in headers
        assert headers["Accept"] == "application/json"


class TestMapResponse:
    """Traduction des réponses HTTP en résultats ou exceptions métier."""

    def test_succes_renvoie_le_corps_json(self, api_client: BaseAPIClient) -> None:
        response = httpx.Response(200, json={"id": 1})
        assert api_client._map_response(response) == {"id": 1}

    def test_204_renvoie_true(self, api_client: BaseAPIClient) -> None:
        assert api_client._map_response(httpx.Response(204)) is True

    def test_401_purge_la_session_avant_de_lever(
        self, api_client: BaseAPIClient
    ) -> None:
        session = api_client.request.session
        session["is_authenticated"] = True
        session["jwt_token"] = "jeton-perime"

        with pytest.raises(TokenExpiredError):
            api_client._map_response(httpx.Response(401))

        assert "is_authenticated" not in session
        assert "Votre session a expiré. Veuillez vous reconnecter." in [
            str(m) for m in get_messages(api_client.request)
        ]

    def test_404_leve_ressource_introuvable(self, api_client: BaseAPIClient) -> None:
        with pytest.raises(ResourceNotFoundError):
            api_client._map_response(httpx.Response(404))

    def test_409_conserve_le_detail_du_conflit(self, api_client: BaseAPIClient) -> None:
        response = httpx.Response(
            409, json={"detail": "Un client avec ce SIRET existe déjà."}
        )
        with pytest.raises(ResourceConflictError) as exc_info:
            api_client._map_response(response)
        assert exc_info.value.detail == "Un client avec ce SIRET existe déjà."

    def test_422_conserve_le_detail_de_validation(
        self, api_client: BaseAPIClient
    ) -> None:
        detail = [{"loc": ["body", "siret"], "msg": "SIRET invalide."}]
        with pytest.raises(APIValidationError) as exc_info:
            api_client._map_response(httpx.Response(422, json={"detail": detail}))
        assert exc_info.value.detail == detail

    def test_500_leve_server_error_avec_detail(self, api_client: BaseAPIClient) -> None:
        with pytest.raises(ServerError) as exc_info:
            api_client._map_response(
                httpx.Response(500, json={"detail": "Erreur interne."})
            )
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Erreur interne."

    def test_403_leve_erreur_generique_avec_detail(
        self, api_client: BaseAPIClient
    ) -> None:
        """Les 403 métier portent un garde-fou explicite, relayé aux vues."""
        with pytest.raises(APIClientError) as exc_info:
            api_client._map_response(
                httpx.Response(403, json={"detail": "Ce compte est protégé."})
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Ce compte est protégé."

    def test_corps_non_json_donne_un_detail_absent(
        self, api_client: BaseAPIClient
    ) -> None:
        response = httpx.Response(409, content=b"<html>Bad Gateway</html>")
        with pytest.raises(ResourceConflictError) as exc_info:
            api_client._map_response(response)
        assert exc_info.value.detail is None


class TestPolitiqueDeRejeu:
    """Rejeu des erreurs transitoires : idempotence obligatoire."""

    def test_get_rejoue_un_502_puis_reussit(
        self, api_client: BaseAPIClient, httpx_mock: Any
    ) -> None:
        calls = httpx_mock([httpx.Response(502), httpx.Response(200, json=[])])

        assert api_client.get("/clients/") == []
        assert len(calls) == 2

    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_get_epuise_ses_rejeux_sur_erreur_persistante(
        self, api_client: BaseAPIClient, httpx_mock: Any, status: int
    ) -> None:
        calls = httpx_mock([httpx.Response(status)] * 3)

        with pytest.raises(APIUnavailableError) as exc_info:
            api_client.get("/clients/")

        # 1 tentative initiale + 2 rejeux, puis l'erreur porte le statut.
        assert len(calls) == 3
        assert exc_info.value.status_code == status

    def test_get_rejoue_une_erreur_reseau_puis_reussit(
        self, api_client: BaseAPIClient, httpx_mock: Any
    ) -> None:
        calls = httpx_mock(
            [httpx.ConnectError("connexion refusée"), httpx.Response(200, json=[])]
        )

        assert api_client.get("/clients/") == []
        assert len(calls) == 2

    def test_get_erreur_reseau_persistante_leve_indisponible(
        self, api_client: BaseAPIClient, httpx_mock: Any
    ) -> None:
        calls = httpx_mock([httpx.ConnectError("connexion refusée")] * 3)

        with pytest.raises(APIUnavailableError):
            api_client.get("/clients/")
        assert len(calls) == 3

    def test_post_ne_rejoue_jamais_un_502(
        self, api_client: BaseAPIClient, httpx_mock: Any
    ) -> None:
        """Un POST 502 remonte en ServerError avec son detail (ex. Chorus Pro)."""
        calls = httpx_mock(
            [httpx.Response(502, json={"detail": "Dépôt refusé par Chorus Pro."})]
        )

        with pytest.raises(ServerError) as exc_info:
            api_client.post("/factures/1/transmettre-choruspro", {})

        assert len(calls) == 1
        assert exc_info.value.status_code == 502
        assert exc_info.value.detail == "Dépôt refusé par Chorus Pro."

    def test_post_erreur_reseau_leve_indisponible_sans_rejeu(
        self, api_client: BaseAPIClient, httpx_mock: Any
    ) -> None:
        calls = httpx_mock([httpx.ConnectError("connexion refusée")])

        with pytest.raises(APIUnavailableError):
            api_client.post("/clients/", {})
        assert len(calls) == 1

    def test_les_en_tetes_de_session_partent_avec_la_requete(
        self, api_client: BaseAPIClient, httpx_mock: Any
    ) -> None:
        api_client.request.session["jwt_token"] = "jeton-jwt"
        api_client.request.session["entreprise_id"] = 42
        calls = httpx_mock([httpx.Response(200, json={})])

        api_client.get("/clients/")

        headers = calls[0]["headers"]
        assert headers["Authorization"] == "Bearer jeton-jwt"
        assert headers["x-entreprise-id"] == "42"
        assert calls[0]["url"].endswith("/clients/")


class TestCompteurTelemetrie:
    """Le compteur d'API injoignable est tenu par la couche cliente elle-même.

    L'instrumentation httpx n'enregistre aucune métrique quand la connexion
    échoue : `BaseAPIClient` appelle `count_api_unavailable` à chaque échec
    définitif (voir `config/telemetry.py`). On vérifie ici le branchement,
    pas le pipeline OpenTelemetry.
    """

    @pytest.fixture
    def compteur_espion(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        """Remplace le compteur du module télémétrie par un espion."""
        from config import telemetry

        appels: list[int] = []

        class FauxCompteur:
            def add(self, valeur: int) -> None:
                appels.append(valeur)

        monkeypatch.setattr(telemetry, "_api_unavailable_counter", FauxCompteur())
        return appels

    def test_echec_reseau_definitif_compte_une_fois(
        self, api_client: BaseAPIClient, httpx_mock: Any, compteur_espion: list[int]
    ) -> None:
        # 3 tentatives (1 + 2 rejeux), toutes en erreur réseau : un seul
        # échec définitif doit être compté, pas un par tentative.
        httpx_mock([httpx.ConnectError("refusée")] * 3)

        with pytest.raises(APIUnavailableError):
            api_client.get("/clients/")
        assert compteur_espion == [1]

    def test_reponse_obtenue_ne_compte_rien(
        self, api_client: BaseAPIClient, httpx_mock: Any, compteur_espion: list[int]
    ) -> None:
        # Une réponse 5xx N'EST PAS un échec de connexion : elle est déjà
        # visible dans les métriques standard de l'instrumentation httpx.
        httpx_mock([httpx.Response(500, json={"detail": "boom"})])

        with pytest.raises(ServerError):
            api_client.get("/clients/")
        assert compteur_espion == []
