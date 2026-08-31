"""Télémétrie du client web (OpenTelemetry) — désactivée par défaut.

Même schéma que `factur-ia-api-data` : deux interrupteurs indépendants, lus
dans l'environnement (le `.env` est exporté par `load_dotenv()` aux points
d'entrée, et le SDK OpenTelemetry lit lui aussi `os.environ`) :

- ``OTEL_ENABLED`` : traces (export OTLP/HTTP vers un collector).
- ``OTEL_METRICS_ENABLED`` : métriques + endpoint ``/metrics`` (format
  Prometheus, mode pull : c'est Prometheus qui vient lire, aucun collector).

Si aucun des deux n'est actif, `setup_telemetry()` retourne immédiatement
sans même importer le SDK : rien ne change en local ni en CI. Un collector
injoignable ne casse jamais l'application : l'export des traces se fait en
tâche de fond (`BatchSpanProcessor`) et ses erreurs sont mises en sourdine.

Données sensibles — garanties :

- les en-têtes HTTP ne sont jamais capturés (ne jamais définir les variables
  ``OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*`` : le JWT ``Authorization``
  et ``x-entreprise-id`` fuiteraient) ;
- les corps de requête/réponse ne sont pas supportés par les
  instrumentations, donc jamais capturés ;
- les query strings sont retirées des attributs d'URL par les hooks de
  scrubbing ci-dessous (une recherche SIRENE relayée porte un SIRET en
  query) ;
- les labels de métriques sont à cardinalité bornée : route templatée côté
  serveur (jamais l'ID réel), hôte/port côté client (jamais le chemin).
"""

import logging
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Span
    from prometheus_client import CollectorRegistry

# Registre Prometheus dédié (jamais le registre global de prometheus_client),
# créé par `_build_meter_provider` seulement si OTEL_METRICS_ENABLED est vrai.
_registry: "CollectorRegistry | None" = None

# Garde d'idempotence : `setup_telemetry()` est appelée depuis chaque point
# d'entrée (manage.py, wsgi.py, asgi.py) mais ne doit instrumenter qu'une fois.
_initialized = False

# Compteur des échecs définitifs de connexion à l'API data (voir
# `_build_meter_provider`) ; reste `None` tant que les métriques sont
# désactivées, et `count_api_unavailable` est alors un no-op.
_api_unavailable_counter: Any = None


def count_api_unavailable() -> None:
    """Compte un échec définitif de connexion à l'API data (après rejeux).

    Appelée par `clients.base_client` au moment où il lève
    `APIUnavailableError`. No-op strict si les métriques sont désactivées.
    """
    if _api_unavailable_counter is not None:
        _api_unavailable_counter.add(1)


def _env_flag(name: str) -> bool:
    """Lit un booléen dans l'environnement (défaut faux), à la façon de DEBUG.

    Args:
        name (str): Nom de la variable d'environnement. Obligatoire.

    Returns:
        bool: `True` si la variable vaut « true » (insensible à la casse).
    """
    return os.getenv(name, "False").lower() == "true"


def scrub_url(url: object) -> str:
    """Réduit une URL à « schéma://hôte/chemin » (sans credentials ni query).

    Args:
        url (object): URL complète, telle que posée par une instrumentation.
            Obligatoire.

    Returns:
        str: URL nettoyée : ni ``user:pass@``, ni query string (un SIRET peut
        s'y trouver), ni fragment.
    """
    parts = urlsplit(str(url))
    netloc = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _scrub_span_url_attributes(span: "Span") -> None:
    """Réécrit les attributs d'URL d'un span, sans query string.

    Couvre les deux générations de conventions sémantiques : ``http.url``
    (ancienne), ``url.full`` et ``url.query`` (stables).

    Args:
        span (Span): Span en cours d'enregistrement. Obligatoire.
    """
    attributes = getattr(span, "attributes", None) or {}
    for key in ("http.url", "url.full"):
        value = attributes.get(key)
        if value is not None:
            span.set_attribute(key, scrub_url(value))
    if "url.query" in attributes:
        span.set_attribute("url.query", "")


def _server_response_hook(span: "Span", request: Any, response: Any) -> None:
    """Hook Django (fin de requête entrante) : nettoie les URLs du span."""
    _scrub_span_url_attributes(span)


def _client_request_hook(span: "Span", request_info: Any) -> None:
    """Hook httpx (appel sortant vers l'API data) : nettoie les URLs du span."""
    _scrub_span_url_attributes(span)


async def _async_client_request_hook(span: "Span", request_info: Any) -> None:
    """Variante async du hook httpx (clients `httpx.AsyncClient`)."""
    _scrub_span_url_attributes(span)


def _build_tracer_provider() -> "TracerProvider":
    """Construit et installe le pipeline de traces (export OTLP ou console).

    Returns:
        TracerProvider: Provider installé globalement, export en tâche de
        fond ; un collector injoignable ne bloque jamais une requête.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
    )

    # Un collector absent provoquerait des logs d'erreur en boucle : on
    # muselle les loggers des exporters (l'échec d'export reste silencieux).
    for noisy_logger in (
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.sdk.trace.export",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.CRITICAL)

    exporter: SpanExporter
    if os.getenv("OTEL_TRACES_EXPORTER") == "console":
        # Mode vérification locale sans collector : spans affichés en console.
        exporter = ConsoleSpanExporter()
    else:
        # Export OTLP/HTTP ; l'endpoint est lu par le SDK dans l'environnement
        # (OTEL_EXPORTER_OTLP_ENDPOINT, défaut http://localhost:4318).
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter()

    provider = TracerProvider(
        resource=Resource.create({"service.name": os.environ["OTEL_SERVICE_NAME"]})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def _build_meter_provider() -> "MeterProvider":
    """Construit le pipeline de métriques (registre Prometheus dédié).

    Returns:
        MeterProvider: Provider branché sur un `PrometheusMetricReader` ;
        le registre est conservé au niveau module pour `metrics_view`.
    """
    global _registry, _api_unavailable_counter
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource
    from prometheus_client import CollectorRegistry

    _registry = CollectorRegistry()
    reader = PrometheusMetricReader(registry=_registry)
    provider = MeterProvider(
        resource=Resource.create({"service.name": os.environ["OTEL_SERVICE_NAME"]}),
        metric_readers=[reader],
    )

    # Compteur maison des échecs définitifs de connexion à l'API data.
    # Nécessaire car l'instrumentation httpx n'enregistre AUCUNE métrique
    # quand la connexion échoue (l'exception est relevée avant
    # l'enregistrement de l'histogramme) : sans lui, une API data éteinte
    # serait invisible dans les métriques — le signal le plus important du BFF.
    # Exposé côté Prometheus sous le nom `api_data_unavailable_total`.
    meter = provider.get_meter("config.telemetry")
    _api_unavailable_counter = meter.create_counter(
        "api_data.unavailable",
        unit="1",
        description=(
            "Échecs définitifs de connexion à l'API data (après épuisement des rejeux)"
        ),
    )
    return provider


def metrics_view(request: HttpRequest) -> HttpResponse:
    """Expose le registre Prometheus au format texte (vue de ``/metrics``).

    Endpoint non public : à réserver au scrape Prometheus, ne jamais
    l'exposer tel quel en production.

    Args:
        request (HttpRequest): Requête Django courante. Obligatoire.

    Returns:
        HttpResponse: Le registre au format Prometheus, ou 404 si les
        métriques sont désactivées (comportement neutre par défaut).
    """
    if _registry is None:
        return HttpResponseNotFound()
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return HttpResponse(generate_latest(_registry), content_type=CONTENT_TYPE_LATEST)


def setup_telemetry() -> None:
    """Initialise traces et métriques selon les interrupteurs d'environnement.

    Ne fait strictement rien (aucun import du SDK) si ``OTEL_ENABLED`` et
    ``OTEL_METRICS_ENABLED`` sont tous deux absents ou faux. Idempotente :
    les appels suivants (autres points d'entrée) sont ignorés.
    """
    global _initialized
    otel_enabled = _env_flag("OTEL_ENABLED")
    metrics_enabled = _env_flag("OTEL_METRICS_ENABLED")
    if not (otel_enabled or metrics_enabled):
        return
    if _initialized:
        return
    _initialized = True

    # Défauts relayés au SDK (qui lit os.environ) ; les valeurs déjà posées
    # par le .env ou l'environnement réel restent prioritaires (setdefault).
    os.environ.setdefault("OTEL_SERVICE_NAME", "factur-ia-web")
    # Conventions sémantiques HTTP stables : indispensable pour obtenir le
    # label http_route (route templatée) et des durées en secondes.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    # Exclusions du tracing ET des métriques : /metrics (scrapé toutes les
    # 15 s, aucune valeur) et les fichiers statiques servis par le runserver.
    os.environ.setdefault("OTEL_PYTHON_DJANGO_EXCLUDED_URLS", "metrics$,static/")

    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.metrics import NoOpMeterProvider
    from opentelemetry.trace import NoOpTracerProvider

    # La brique désactivée reçoit un provider no-op explicite (jamais le
    # provider global) : le comportement reste déterministe.
    tracer_provider = _build_tracer_provider() if otel_enabled else NoOpTracerProvider()
    meter_provider = _build_meter_provider() if metrics_enabled else NoOpMeterProvider()

    # Requêtes entrantes (pages du client) : route templatée, statut, durée.
    DjangoInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        response_hook=_server_response_hook,
    )
    # Appels sortants vers l'API data : patch global de httpx.Client, la
    # couche clients/ est couverte sans modifier son code.
    HTTPXClientInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        request_hook=_client_request_hook,
        async_request_hook=_async_client_request_hook,
    )
