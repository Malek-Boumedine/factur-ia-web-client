"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from dotenv import load_dotenv


load_dotenv()

env = os.getenv("DJANGO_ENV", "dev")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{env}")

# Télémétrie (no-op si OTEL_ENABLED/OTEL_METRICS_ENABLED sont absents) :
# posée avant la création de l'application pour instrumenter dès le départ.
from config.telemetry import setup_telemetry  # noqa: E402

setup_telemetry()

application = get_asgi_application()
