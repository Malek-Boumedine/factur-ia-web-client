# ruff: noqa: F403, F405
"""Réglages de production — pensés pour Cloud Run derrière le proxy HTTPS Google.

Différences avec la base :
- sessions en base de données (Cloud SQL MySQL, IP privée via egress VPC),
  car le JWT transite en session : ni cookies signés, ni Redis à provisionner ;
- statiques servis par WhiteNoise (fichiers hashés + compression), collectés
  au build de l'image — Django ne sert rien lui-même avec DEBUG=False ;
- sécurité proxy : Cloud Run termine le TLS et parle HTTP à l'application,
  d'où SECURE_PROXY_SSL_HEADER pour que Django sache la requête sécurisée.
"""

import os

import pymysql

from .base import *

# Django ne connaît officiellement que mysqlclient ; PyMySQL (pur Python, donc
# aucun compilateur dans l'image slim) se fait passer pour lui.
pymysql.install_as_MySQLdb()

DEBUG = False

# Les listes venant de l'environnement sont filtrées : une variable absente ou
# vide ne doit pas produire l'entrée "" (rejetée par les checks Django).
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h]

# Obligatoire pour les POST (login, formulaires) : les origines HTTPS du
# service, avec schéma. Ex. : https://factur-ia.example.com
CSRF_TRUSTED_ORIGINS = [
    o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# ==============================================================================
# SESSIONS & BASE DE DONNÉES (Cloud SQL MySQL 8.0)
# ==============================================================================
# Remplace le backend cache (Redis) de la base : en production, les sessions
# vivent dans la table django_session sur Cloud SQL. La table est créée par le
# job de migration dédié (Cloud Run job `factur-ia-migrate-web`) qui exécute :
#   python manage.py migrate --noinput
# — jamais au build (pas d'accès base) ni au démarrage (cold starts).
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# Connexion TCP standard vers l'IP privée de l'instance (egress VPC direct),
# alignée sur le choix fait pour l'API data. Pas de socket /cloudsql/<instance>.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
        # Connexions persistantes : évite un handshake MySQL à chaque requête.
        "CONN_MAX_AGE": 60,
    }
}

# Plus aucun usage de Redis côté web (les sessions étaient son seul usage) :
# cache mémoire local par instance, suffisant pour un BFF sans données métier.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# ==============================================================================
# FICHIERS STATIQUES (WhiteNoise)
# ==============================================================================
# Juste après SecurityMiddleware, comme le recommande WhiteNoise : les statiques
# sont servis au plus tôt, sans traverser sessions/CSRF.
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

# Fichiers hashés (cache navigateur immuable) + variantes compressées,
# générés par `collectstatic` au build de l'image.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# ==============================================================================
# SÉCURITÉ DERRIÈRE LE PROXY HTTPS DE CLOUD RUN
# ==============================================================================
# Cloud Run termine le TLS : l'application ne voit que du HTTP. Ce header posé
# par le proxy permet à request.is_secure() d'être vrai — sans lui, les cookies
# Secure ci-dessous ne seraient jamais émis.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Pas de SECURE_SSL_REDIRECT : Cloud Run n'expose que HTTPS, et une redirection
# forcée casserait les sondes de santé internes (appelées en HTTP).

SESSION_COOKIE_SECURE = True
# Le cookie de session référence le JWT côté serveur : jamais lisible en JS.
# (Défaut Django, explicité car c'est la barrière principale contre le XSS ici.)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True

# HSTS : le navigateur n'essaie plus jamais le HTTP. Durée volontairement
# courte au premier déploiement ; à monter vers 31536000 une fois validé.
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# Le Referer ne fuit que l'origine vers les sites tiers.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
