"""Fixtures partagées des tests du client Django (BFF).

Deux briques structurantes :

- les fixtures de « personas » (`client_anonyme`, `client_connecte`, ...) :
  le BFF n'utilise pas `django.contrib.auth`, être connecté se résume à des
  clés de session (`is_authenticated`, `jwt_token`, `entreprise_id`, flags de
  rôle). Chaque fixture renvoie un client de test Django dont la session est
  déjà dans l'état voulu ;
- le harnais `api_mock` : patch des méthodes nommées des classes de la couche
  `clients/` (au niveau de la classe, donc quel que soit le module qui
  l'importe). Aucun test ne touche l'API data réelle — les réponses et les
  exceptions métier (`ResourceNotFoundError`, `APIUnavailableError`, ...) sont
  simulées ici.
"""

import base64
import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

# Alias du journal d'appels renvoyé par `api_mock` : une entrée par appel,
# sous la forme `(args, kwargs)` tels que reçus par la méthode mockée.
ApiCalls = list[tuple[tuple[Any, ...], dict[str, Any]]]
ApiMocker = Callable[..., ApiCalls]


def make_jwt(*, expires_in: int = 3600) -> str:
    """Forge un JWT non signé portant un claim `exp` relatif à maintenant.

    Suffisant pour le BFF : ni le middleware d'expiration ni la couche cliente
    ne vérifient la signature (le secret appartient à l'API). Trois segments
    base64url sans padding, comme un vrai token.

    Args:
        expires_in (int): Durée de validité en secondes à partir de maintenant.
            Négative pour forger un token déjà expiré. 3600 par défaut.

    Returns:
        str: Un JWT syntaxiquement valide, à poser en session (`jwt_token`).
    """

    def encode(part: dict[str, Any]) -> str:
        raw = json.dumps(part).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": "user@exemple.fr", "exp": int(time.time()) + expires_in}
    return f"{encode(header)}.{encode(payload)}.signature-factice"


def _open_session(django_client: Client, **keys: Any) -> None:
    """Pose des clés dans la session du client de test et l'enregistre.

    Args:
        django_client (Client): Client de test Django cible. Obligatoire.
        **keys: Clés de session à poser telles quelles.
    """
    session = django_client.session
    for key, value in keys.items():
        session[key] = value
    session.save()


@pytest.fixture
def client_anonyme() -> Client:
    """Client de test sans session (visiteur non connecté)."""
    return Client()


@pytest.fixture
def client_connecte() -> Client:
    """Utilisateur connecté rattaché à une entreprise active, sans rôle élevé.

    Ne peut ni gérer l'équipe (`can_manage_team` absent) ni accéder aux pages
    d'administration plateforme.
    """
    django_client = Client()
    _open_session(
        django_client,
        is_authenticated=True,
        jwt_token=make_jwt(),
        user_email="user@exemple.fr",
        entreprise_id=1,
        is_platform_admin=False,
        is_entreprise_admin=False,
        can_manage_team=False,
    )
    return django_client


@pytest.fixture
def client_sans_entreprise() -> Client:
    """Utilisateur connecté sans entreprise active (onboarding non fait)."""
    django_client = Client()
    _open_session(
        django_client,
        is_authenticated=True,
        jwt_token=make_jwt(),
        user_email="user@exemple.fr",
        is_platform_admin=False,
        is_entreprise_admin=False,
        can_manage_team=False,
    )
    return django_client


@pytest.fixture
def client_admin_plateforme() -> Client:
    """Administrateur de plateforme, non rattaché à une entreprise."""
    django_client = Client()
    _open_session(
        django_client,
        is_authenticated=True,
        jwt_token=make_jwt(),
        user_email="admin@exemple.fr",
        is_platform_admin=True,
        is_entreprise_admin=False,
        can_manage_team=False,
    )
    return django_client


@pytest.fixture
def client_proprietaire() -> Client:
    """Propriétaire de l'entreprise active (peut gérer l'équipe)."""
    django_client = Client()
    _open_session(
        django_client,
        is_authenticated=True,
        jwt_token=make_jwt(),
        user_email="proprietaire@exemple.fr",
        entreprise_id=1,
        is_platform_admin=False,
        is_entreprise_admin=True,
        can_manage_team=True,
    )
    return django_client


@pytest.fixture
def api_mock(monkeypatch: pytest.MonkeyPatch) -> ApiMocker:
    """Fabrique de mocks pour les méthodes des classes clientes (`clients/`).

    Patch la méthode au niveau de la classe : le mock s'applique quel que soit
    le module de vue qui a importé la classe. Échoue immédiatement si la
    méthode n'existe pas (protection contre les fautes de frappe : on ne mocke
    jamais une méthode fantôme).

    Usage::

        calls = api_mock(FacturesClient, "get_facture", returns={"id": 1})
        api_mock(FacturesClient, "delete_invoice", raises=ResourceNotFoundError())

    Returns:
        ApiMocker: Fonction `(client_cls, method_name, *, returns, raises)`
        renvoyant le journal des appels reçus (liste de `(args, kwargs)`),
        pour asserter les payloads envoyés — ou l'absence d'appel.
    """

    def _install(
        client_cls: type,
        method_name: str,
        *,
        returns: Any = None,
        raises: BaseException | None = None,
    ) -> ApiCalls:
        calls: ApiCalls = []

        def fake(self: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append((args, kwargs))
            if raises is not None:
                raise raises
            return returns

        # `monkeypatch.setattr` exige que l'attribut existe déjà : c'est le
        # garde-fou contre le mock d'une méthode inexistante.
        monkeypatch.setattr(client_cls, method_name, fake)
        return calls

    return _install
