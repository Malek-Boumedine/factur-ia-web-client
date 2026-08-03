"""Tests de la télémétrie (config/telemetry.py).

Trois garanties vérifiées :

- **neutralité par défaut** : sans interrupteur d'environnement, l'appel de
  `setup_telemetry()` ne fait rien (aucune instrumentation, pas de registre) ;
- **scrubbing** : `scrub_url` retire credentials, query string (un SIRET peut
  s'y trouver) et fragment des URLs enregistrées dans les spans ;
- **endpoint /metrics** : 404 tant que les métriques sont désactivées, format
  Prometheus quand le registre existe.

Le chemin « activé » est testé avec l'interrupteur métriques seul (pas de
traces : aucun exporter réseau à simuler), puis dés-instrumenté pour ne pas
polluer les autres tests.
"""

import pytest
from django.test import Client

from config import telemetry


@pytest.fixture
def telemetry_state(monkeypatch: pytest.MonkeyPatch):
    """Isole l'état module de la télémétrie (globals remis à zéro après)."""
    monkeypatch.setattr(telemetry, "_initialized", False)
    monkeypatch.setattr(telemetry, "_registry", None)
    # Aucun interrupteur hérité de l'environnement du développeur.
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_METRICS_ENABLED", raising=False)
    return monkeypatch


class TestInterrupteurs:
    """Le défaut est un no-op strict : rien ne change en local ni en CI."""

    def test_defaut_desactive(self, telemetry_state: pytest.MonkeyPatch) -> None:
        telemetry.setup_telemetry()
        assert telemetry._initialized is False
        assert telemetry._registry is None

    def test_valeur_fausse_explicite(self, telemetry_state: pytest.MonkeyPatch) -> None:
        telemetry_state.setenv("OTEL_ENABLED", "False")
        telemetry_state.setenv("OTEL_METRICS_ENABLED", "false")
        telemetry.setup_telemetry()
        assert telemetry._initialized is False

    def test_metriques_activees_puis_desinstrumentees(
        self, telemetry_state: pytest.MonkeyPatch
    ) -> None:
        """Chemin activé : registre créé, instrumentations posées puis retirées."""
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        telemetry_state.setenv("OTEL_METRICS_ENABLED", "True")
        try:
            telemetry.setup_telemetry()
            assert telemetry._initialized is True
            assert telemetry._registry is not None
            # Idempotence : un second appel (autre point d'entrée) est ignoré.
            registre = telemetry._registry
            telemetry.setup_telemetry()
            assert telemetry._registry is registre
        finally:
            DjangoInstrumentor().uninstrument()
            HTTPXClientInstrumentor().uninstrument()


class TestCompteurApiInjoignable:
    """Compteur maison des échecs définitifs de connexion à l'API data."""

    def test_no_op_si_metriques_desactivees(
        self, telemetry_state: pytest.MonkeyPatch
    ) -> None:
        telemetry_state.setattr(telemetry, "_api_unavailable_counter", None)
        # Ne doit ni compter ni lever : c'est un no-op strict.
        telemetry.count_api_unavailable()

    def test_incremente_le_compteur_quand_present(
        self, telemetry_state: pytest.MonkeyPatch
    ) -> None:
        appels: list[int] = []

        class FauxCompteur:
            def add(self, valeur: int) -> None:
                appels.append(valeur)

        telemetry_state.setattr(telemetry, "_api_unavailable_counter", FauxCompteur())
        telemetry.count_api_unavailable()
        assert appels == [1]


class TestScrubUrl:
    """Réduction des URLs à « schéma://hôte/chemin », sans donnée sensible."""

    def test_query_string_retiree(self) -> None:
        # Cas réel : recherche SIRENE relayée avec un SIRET en query.
        url = "http://api.example/entreprises/recherche?siret=12345678900011"
        assert telemetry.scrub_url(url) == "http://api.example/entreprises/recherche"

    def test_credentials_retires(self) -> None:
        # Faux credentials volontaires : le test vérifie qu'ils sont retirés.
        assert (
            telemetry.scrub_url(
                "https://user:secret@api.example/route"  # pragma: allowlist secret
            )
            == "https://api.example/route"
        )

    def test_fragment_retire(self) -> None:
        assert telemetry.scrub_url("http://h/p#frag") == "http://h/p"

    def test_url_sans_query_inchangee(self) -> None:
        assert (
            telemetry.scrub_url("http://h:8080/factures/") == "http://h:8080/factures/"
        )


class TestMetricsView:
    """L'endpoint /metrics est neutre par défaut, Prometheus sinon."""

    def test_404_par_defaut(self, telemetry_state: pytest.MonkeyPatch) -> None:
        reponse = Client().get("/metrics")
        assert reponse.status_code == 404

    def test_200_quand_le_registre_existe(
        self, telemetry_state: pytest.MonkeyPatch
    ) -> None:
        from prometheus_client import CollectorRegistry

        telemetry_state.setattr(telemetry, "_registry", CollectorRegistry())
        reponse = Client().get("/metrics")
        assert reponse.status_code == 200
        assert reponse["Content-Type"].startswith("text/plain")
