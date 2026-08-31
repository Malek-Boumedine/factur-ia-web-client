"""Tests du jeton d'identité Google pour l'IAM Cloud Run (`gcp_identity`).

L'obtention du jeton (`fetch_id_token`) est systématiquement mockée : aucun
test ne touche le réseau ni ne suppose un serveur de métadonnées. On vérifie :

- l'interrupteur `API_IAM_AUTH_ENABLED` : désactivé (défaut des settings de
  test), le module renvoie `{}` sans la moindre tentative d'obtention ;
- le format de l'en-tête produit quand il est activé ;
- le cache : un jeton valide n'est jamais redemandé, un jeton expiré (ou à
  moins de 5 minutes de l'être) est renouvelé ;
- le repli quand la claim `exp` du jeton est illisible ;
- la traduction de tout échec d'obtention en `APIUnavailableError`.
"""

import base64
import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from pytest_django.fixtures import SettingsWrapper

from clients import gcp_identity
from clients.exceptions import APIUnavailableError


def _fake_token(exp: float) -> str:
    """Forge un pseudo-JWT dont seule la claim `exp` du payload est réaliste."""
    payload = json.dumps({"exp": exp}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return f"entete.{payload_b64}.signature"


@pytest.fixture(autouse=True)
def cache_vierge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repart d'un cache vide : le cache est module-niveau, donc inter-tests."""
    monkeypatch.setattr(gcp_identity, "_cached_token", None)
    monkeypatch.setattr(gcp_identity, "_cached_expiry", 0.0)


@pytest.fixture
def fetch_espion(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], list[str]]:
    """Remplace `fetch_id_token` par une séquence programmée d'issues.

    Chaque issue est soit un jeton (str, renvoyé), soit une exception (levée).

    Returns:
        Fonction `(outcomes) -> journal` : installe la séquence et renvoie le
        journal des audiences demandées (une entrée par tentative d'obtention).
    """

    def _install(outcomes: list[Any]) -> list[str]:
        remaining = list(outcomes)
        calls: list[str] = []

        def fake_fetch(request: Any, audience: str) -> str:
            calls.append(audience)
            assert remaining, "fetch_id_token appelé plus souvent que prévu"
            outcome = remaining.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return str(outcome)

        monkeypatch.setattr(gcp_identity, "fetch_id_token", fake_fetch)
        return calls

    return _install


class TestInterrupteur:
    """`API_IAM_AUTH_ENABLED` gouverne tout : rien ne part, rien n'est tenté."""

    def test_desactive_renvoie_vide_sans_obtention(
        self, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        # Défaut des settings de test : API_IAM_AUTH_ENABLED = False.
        calls = fetch_espion([])

        assert gcp_identity.serverless_authorization_header() == {}
        assert calls == []

    def test_active_construit_l_en_tete_bearer(
        self, settings: SettingsWrapper, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        settings.API_IAM_AUTH_ENABLED = True
        fetch_espion([_fake_token(time.time() + 3600)])

        header = gcp_identity.serverless_authorization_header()

        assert list(header) == ["X-Serverless-Authorization"]
        assert header["X-Serverless-Authorization"].startswith("Bearer entete.")

    def test_l_audience_est_l_url_de_l_api(
        self, settings: SettingsWrapper, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        settings.API_IAM_AUTH_ENABLED = True
        calls = fetch_espion([_fake_token(time.time() + 3600)])

        gcp_identity.serverless_authorization_header()

        # Cloud Run vérifie l'audience côté API data : c'est l'URL du service.
        assert calls == ["http://api-de-test.local"]


class TestCache:
    """Un jeton vaut une heure : on ne redemande qu'à l'approche de l'expiration."""

    @pytest.fixture(autouse=True)
    def iam_active(self, settings: SettingsWrapper) -> None:
        settings.API_IAM_AUTH_ENABLED = True

    def test_jeton_valide_jamais_redemande(
        self, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        calls = fetch_espion([_fake_token(time.time() + 3600)])

        premier = gcp_identity.serverless_authorization_header()
        second = gcp_identity.serverless_authorization_header()

        assert premier == second
        assert len(calls) == 1

    def test_jeton_proche_de_l_expiration_est_renouvele(
        self, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        # Premier jeton à moins de 5 minutes (la marge) de son expiration :
        # le second appel doit déclencher un renouvellement.
        calls = fetch_espion(
            [_fake_token(time.time() + 60), _fake_token(time.time() + 3600)]
        )

        gcp_identity.serverless_authorization_header()
        gcp_identity.serverless_authorization_header()

        assert len(calls) == 2

    def test_claim_exp_illisible_donne_un_repli_d_une_heure(
        self, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        # Jeton sans structure JWT : l'expiration est supposée à une heure,
        # donc le jeton reste servi depuis le cache aux appels suivants.
        calls = fetch_espion(["jeton-opaque-sans-payload"])

        gcp_identity.serverless_authorization_header()
        gcp_identity.serverless_authorization_header()

        assert len(calls) == 1


class TestEchecs:
    """Sans jeton, l'API est de fait injoignable : exception déjà gérée en vues."""

    @pytest.fixture(autouse=True)
    def iam_active(self, settings: SettingsWrapper) -> None:
        settings.API_IAM_AUTH_ENABLED = True

    def test_echec_d_obtention_leve_api_indisponible(
        self, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        fetch_espion([RuntimeError("serveur de métadonnées injoignable")])

        with pytest.raises(APIUnavailableError):
            gcp_identity.serverless_authorization_header()

    def test_un_echec_n_empoisonne_pas_le_cache(
        self, fetch_espion: Callable[[list[Any]], list[str]]
    ) -> None:
        # Après un échec, l'appel suivant retente l'obtention et réussit.
        calls = fetch_espion(
            [RuntimeError("injoignable"), _fake_token(time.time() + 3600)]
        )

        with pytest.raises(APIUnavailableError):
            gcp_identity.serverless_authorization_header()
        header = gcp_identity.serverless_authorization_header()

        assert "X-Serverless-Authorization" in header
        assert len(calls) == 2
