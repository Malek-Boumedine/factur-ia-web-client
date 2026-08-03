# ruff: noqa: F403, F405
from .base import *

DEBUG = False

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
