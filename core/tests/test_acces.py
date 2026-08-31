"""Tests de la gestion des accès (gardes de vues, middleware d'expiration).

Couvre les quatre barrières du BFF :

- `_guard_entreprise` : pages métier exigeant une entreprise active ;
- `_guard_platform_admin` (et son équivalent inline sur la page admins) :
  pages réservées aux administrateurs de plateforme ;
- le gate `can_manage_team` de la page équipe ;
- `SessionExpiryMiddleware` : purge de session sur JWT expiré.

Plus les actions destructrices POST-only : un GET ne doit jamais déclencher
d'effet de bord (405 via `@require_POST`, ou redirection sans appel API pour
les vues à contrôle manuel).
"""

from datetime import UTC, datetime
from typing import Any

from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

import pytest

from clients.abonnements_client import AbonnementsClient
from clients.admins_plateforme_client import AdminsPlateformeClient
from clients.clients_client import ClientsClient
from clients.documents_client import DocumentsClient
from clients.factures_client import FacturesClient
from clients.utilisateurs_client import UtilisateursClient
from core.middleware import _MSG_SESSION_EXPIREE, get_token_expiry
from core.tests.conftest import ApiMocker, make_jwt
from core.views.admins_plateforme import _MSG_ACCES_REFUSE
from core.views.auth import _MSG_PAGE_ENTREPRISE
from core.views.equipe import _MSG_ACCES_EQUIPE


def _messages_of(response: Any) -> list[str]:
    """Extrait les messages Django déposés pendant le traitement de la requête.

    Le paramètre est typé `Any` : le client de test renvoie un type de réponse
    interne à django-stubs, non importable proprement.
    """
    return [str(m) for m in get_messages(response.wsgi_request)]


# Toutes les pages protégées accessibles en GET : un visiteur anonyme doit
# systématiquement être renvoyé vers la connexion, quelle que soit la garde
# (entreprise, admin plateforme ou simple authentification).
PROTECTED_GET_URLS = [
    ("clients", {}),
    ("client_create", {}),
    ("client_detail", {"client_id": 1}),
    ("client_update", {"client_id": 1}),
    ("catalogue", {}),
    ("catalogue_create", {}),
    ("catalogue_detail", {"produit_id": 1}),
    ("catalogue_update", {"produit_id": 1}),
    ("documents", {}),
    ("upload_document", {}),
    ("document_fichier", {"document_id": 1}),
    ("document_attente", {"document_id": 1}),
    ("document_delete", {"document_id": 1}),
    ("factures", {}),
    ("facture_recap", {"facture_id": 1}),
    ("facture_apercu", {"facture_id": 1}),
    ("facture_facturx", {"facture_id": 1}),
    ("facture_delete", {"facture_id": 1}),
    ("facture_avoir", {"facture_id": 1}),
    ("facture_transmettre_choruspro", {"facture_id": 1}),
    ("dashboard", {}),
    ("statistiques", {}),
    ("abonnements", {}),
    ("equipe", {}),
    ("profil", {}),
    ("acces", {}),
    ("admins_plateforme", {}),
    ("admin_entreprises", {}),
    ("admin_entreprise_detail", {"entreprise_id": 1}),
    ("admin_entreprise_update", {"entreprise_id": 1}),
    ("plans_admin", {}),
    ("plan_create", {}),
    ("plan_update", {"abonnement_id": 1}),
    ("taux_tva_admin", {}),
    ("taux_tva_create", {}),
    ("taux_tva_update", {"taux_tva_id": 1}),
]

# Vues décorées `@require_POST` : un GET doit répondre 405 sans rien exécuter.
POST_ONLY_URLS = [
    ("client_deactivate", {"client_id": 1}),
    ("client_reactivate", {"client_id": 1}),
    ("catalogue_deactivate", {"produit_id": 1}),
    ("catalogue_reactivate", {"produit_id": 1}),
    ("abonnement_changer", {"abonnement_id": 1}),
    ("abonnement_prolonger", {}),
    ("plan_delete", {"abonnement_id": 1}),
    ("taux_tva_deactivate", {"taux_tva_id": 1}),
    ("taux_tva_reactivate", {"taux_tva_id": 1}),
    ("admin_entreprise_change_plan", {"entreprise_id": 1}),
    ("admin_entreprise_extend", {"entreprise_id": 1}),
    ("admin_entreprise_cancel", {"entreprise_id": 1}),
    ("admin_entreprise_delete", {"entreprise_id": 1}),
    ("admin_entreprise_suspend", {"entreprise_id": 1}),
    ("admin_entreprise_reactivate", {"entreprise_id": 1}),
]


class TestAccesAnonyme:
    """Un visiteur non connecté est renvoyé vers la connexion partout."""

    @pytest.mark.parametrize(
        ("url_name", "url_kwargs"),
        PROTECTED_GET_URLS,
        ids=[name for name, _ in PROTECTED_GET_URLS],
    )
    def test_page_protegee_redirige_vers_login(
        self, client_anonyme: Client, url_name: str, url_kwargs: dict
    ) -> None:
        response = client_anonyme.get(reverse(url_name, kwargs=url_kwargs))
        assert response.status_code == 302
        assert response["Location"] == reverse("login")

    def test_statut_document_renvoie_401_json(self, client_anonyme: Client) -> None:
        """Le endpoint de polling répond en JSON (pas de redirection HTML)."""
        response = client_anonyme.get(
            reverse("document_statut", kwargs={"document_id": 1})
        )
        assert response.status_code == 401
        corps = response.json()
        assert corps["statut"] == "session_expiree"
        assert corps["url_redirection"] == reverse("login")


class TestGuardEntreprise:
    """Pages métier : une entreprise active en session est exigée."""

    def test_connecte_sans_entreprise_redirige_vers_onboarding(
        self, client_sans_entreprise: Client
    ) -> None:
        response = client_sans_entreprise.get(reverse("clients"))
        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")

    def test_admin_plateforme_sans_entreprise_redirige_vers_plans(
        self, client_admin_plateforme: Client
    ) -> None:
        """L'admin plateforme n'est pas forcé à l'onboarding : plans + message."""
        response = client_admin_plateforme.get(reverse("clients"))
        assert response.status_code == 302
        assert response["Location"] == reverse("plans_admin")
        assert _MSG_PAGE_ENTREPRISE in _messages_of(response)

    def test_connecte_avec_entreprise_accede(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(ClientsClient, "list_clients", returns={"items": [], "total": 0})
        response = client_connecte.get(reverse("clients"))
        assert response.status_code == 200


class TestGuardPlatformAdmin:
    """Pages d'administration plateforme : flag `is_platform_admin` exigé."""

    @pytest.mark.parametrize(
        "url_name", ["plans_admin", "taux_tva_admin", "admin_entreprises"]
    )
    def test_non_admin_renvoye_vers_home_avec_message(
        self, client_connecte: Client, url_name: str
    ) -> None:
        response = client_connecte.get(reverse(url_name))
        assert response.status_code == 302
        assert response["Location"] == reverse("home")
        assert _MSG_ACCES_REFUSE in _messages_of(response)

    def test_admin_plateforme_accede_aux_plans(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AbonnementsClient, "list_subscriptions", returns=[])
        response = client_admin_plateforme.get(reverse("plans_admin"))
        assert response.status_code == 200

    def test_non_admin_refuse_sur_la_page_admins(self, client_connecte: Client) -> None:
        """La page admins porte sa garde inline : même comportement attendu."""
        response = client_connecte.get(reverse("admins_plateforme"))
        assert response.status_code == 302
        assert response["Location"] == reverse("home")
        assert _MSG_ACCES_REFUSE in _messages_of(response)

    def test_admin_plateforme_accede_a_la_page_admins(
        self, client_admin_plateforme: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(AdminsPlateformeClient, "list_admins", returns=[])
        response = client_admin_plateforme.get(reverse("admins_plateforme"))
        assert response.status_code == 200


class TestAccesEquipe:
    """Page équipe : réservée aux rôles autorisés (`can_manage_team`)."""

    def test_role_insuffisant_renvoye_vers_home_avec_message(
        self, client_connecte: Client
    ) -> None:
        response = client_connecte.get(reverse("equipe"))
        assert response.status_code == 302
        assert response["Location"] == reverse("home")
        assert _MSG_ACCES_EQUIPE in _messages_of(response)

    def test_proprietaire_accede(
        self, client_proprietaire: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(UtilisateursClient, "get_roles", returns=[])
        api_mock(UtilisateursClient, "get_equipe", returns=[])
        response = client_proprietaire.get(reverse("equipe"))
        assert response.status_code == 200


class TestSessionExpiryMiddleware:
    """Purge de session dès que le JWT porté est expiré."""

    @staticmethod
    def _client_avec_jwt(token: object) -> Client:
        django_client = Client()
        session = django_client.session
        session["is_authenticated"] = True
        session["jwt_token"] = token
        session.save()
        return django_client

    def test_jwt_expire_purge_la_session_et_previent(self, api_mock: ApiMocker) -> None:
        api_mock(AbonnementsClient, "list_subscriptions", returns=[])
        django_client = self._client_avec_jwt(make_jwt(expires_in=-60))

        response = django_client.get(reverse("home"))

        assert response.status_code == 200
        assert "is_authenticated" not in django_client.session
        assert _MSG_SESSION_EXPIREE in _messages_of(response)

    def test_jwt_valide_laisse_la_session_intacte(self, api_mock: ApiMocker) -> None:
        api_mock(AbonnementsClient, "list_subscriptions", returns=[])
        django_client = self._client_avec_jwt(make_jwt(expires_in=3600))

        django_client.get(reverse("home"))

        assert django_client.session.get("is_authenticated") is True

    @pytest.mark.parametrize(
        "token",
        [None, "pas-un-jwt", "a.b", "a.%%%.c"],
        ids=["absent", "sans-points", "deux-segments", "base64-invalide"],
    )
    def test_jwt_illisible_laisse_la_session_intacte(
        self, api_mock: ApiMocker, token: object
    ) -> None:
        """Prudence volontaire : on ne déconnecte jamais faute d'information."""
        api_mock(AbonnementsClient, "list_subscriptions", returns=[])
        django_client = self._client_avec_jwt(token)

        django_client.get(reverse("home"))

        assert django_client.session.get("is_authenticated") is True


class TestGetTokenExpiry:
    """Décodage du claim `exp` : tolérant à toutes les entrées inexploitables."""

    def test_renvoie_la_date_exp_en_utc(self) -> None:
        token = make_jwt(expires_in=3600)
        expiry = get_token_expiry(token)
        assert expiry is not None
        assert expiry.tzinfo is UTC
        assert expiry > datetime.now(UTC)

    @pytest.mark.parametrize(
        "token",
        [None, 42, "abc", "a.b.c.d", make_jwt().replace(".", "!")],
        ids=["none", "entier", "sans-segments", "quatre-segments", "mal-forme"],
    )
    def test_renvoie_none_pour_un_token_inexploitable(self, token: object) -> None:
        assert get_token_expiry(token) is None

    def test_renvoie_none_sans_claim_exp_numerique(self) -> None:
        """Un `exp` non numérique (ou booléen) n'est pas une date exploitable."""
        import base64
        import json

        def forge(payload: dict) -> str:
            raw = base64.urlsafe_b64encode(json.dumps(payload).encode())
            return f"entete.{raw.rstrip(b'=').decode()}.signature"

        assert get_token_expiry(forge({"sub": "x"})) is None
        assert get_token_expiry(forge({"exp": "demain"})) is None
        assert get_token_expiry(forge({"exp": True})) is None


class TestActionsPostSeulement:
    """Les actions à effet de bord refusent le GET."""

    @pytest.mark.parametrize(
        ("url_name", "url_kwargs"),
        POST_ONLY_URLS,
        ids=[name for name, _ in POST_ONLY_URLS],
    )
    def test_get_refuse_en_405(
        self, client_anonyme: Client, url_name: str, url_kwargs: dict
    ) -> None:
        response = client_anonyme.get(reverse(url_name, kwargs=url_kwargs))
        assert response.status_code == 405

    @pytest.mark.parametrize(
        ("url_name", "client_cls", "method_name", "redirect_name"),
        [
            ("facture_delete", FacturesClient, "delete_invoice", "factures"),
            ("facture_avoir", FacturesClient, "create_credit_note", None),
            (
                "facture_transmettre_choruspro",
                FacturesClient,
                "transmit_to_choruspro",
                None,
            ),
            ("document_delete", DocumentsClient, "delete_document", "documents"),
        ],
        ids=[
            "suppression-facture",
            "avoir",
            "transmission-choruspro",
            "suppression-document",
        ],
    )
    def test_get_redirige_sans_appeler_l_api(
        self,
        client_connecte: Client,
        api_mock: ApiMocker,
        url_name: str,
        client_cls: type,
        method_name: str,
        redirect_name: str | None,
    ) -> None:
        """Vues à contrôle manuel du POST : le GET redirige et n'appelle rien.

        `redirect_name` à `None` : la vue renvoie vers l'aperçu de la facture.
        """
        calls = api_mock(client_cls, method_name, returns=True)
        url_kwargs = (
            {"facture_id": 1} if url_name.startswith("facture") else {"document_id": 1}
        )
        expected = (
            reverse(redirect_name)
            if redirect_name
            else reverse("facture_apercu", kwargs={"facture_id": 1})
        )

        response = client_connecte.get(reverse(url_name, kwargs=url_kwargs))

        assert response.status_code == 302
        assert response["Location"] == expected
        assert calls == []
