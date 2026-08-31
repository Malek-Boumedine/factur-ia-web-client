# ruff: noqa: F403, F405
from .base import *

DEBUG = False

# ==============================================================================
# INDÉPENDANCE VIS-À-VIS DE L'ENVIRONNEMENT
# ==============================================================================
# Les tests doivent tourner à l'identique avec ou sans `.env` (la CI n'en a
# pas) : toute valeur que `base.py` lit dans l'environnement et qui influence
# le comportement des tests est figée ici en dur.

# Clé sans aucune valeur de sécurité : elle ne sert qu'à la signature des
# cookies pendant les tests. En production, la clé reste obligatoire et vient
# de Secret Manager, sans repli.
SECRET_KEY = "cle-de-test-sans-valeur-de-securite"  # noqa: S105  # pragma: allowlist secret

# URL factice : aucun test ne doit toucher le réseau, les clients HTTP sont
# systématiquement mockés.
API_DATA_URL = "http://api-de-test.local"

# Politique de résilience figée : les tests de rejeu comptent les tentatives.
API_CONNECT_TIMEOUT = 5.0
API_READ_TIMEOUT = 15.0
API_MAX_RETRIES = 2

# Authentification IAM Cloud Run désactivée : les tests qui la couvrent
# l'activent explicitement (override_settings), obtention de jeton mockée.
API_IAM_AUTH_ENABLED = False

# Valeurs métier attendues par les tests d'inscription et d'upload.
SIGNUP_DEFAULT_ROLE_ID = 1
DOCUMENT_UPLOAD_MAX_SIZE = 10 * 1024 * 1024

# Niveau de journalisation indépendant d'un éventuel LOG_LEVEL local.
LOGGING["root"] = {"handlers": ["console"], "level": "INFO"}

# Base de données en mémoire vive (détruite à la fin des tests)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Algorithme de hachage ultra-rapide pour ne pas ralentir la création de faux utilisateurs
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Force Celery à exécuter les tâches immédiatement (synchrone) pendant les tests
CELERY_TASK_ALWAYS_EAGER = True

# Cache en mémoire locale : les sessions (SESSION_ENGINE = cache, hérité de
# base) ne dépendent ainsi plus d'un Redis démarré pour exécuter les tests.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Aucune attente entre les rejeux réseau : les tests de résilience de la
# couche cliente ne doivent pas dormir.
API_RETRY_BACKOFF = 0.0
