from .base import *

DEBUG = False

# Base de données en mémoire vive (détruite à la fin des tests)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Algorithme de hachage ultra-rapide pour ne pas ralentir la création de faux utilisateurs
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Force Celery à exécuter les tâches immédiatement (synchrone) pendant les tests
CELERY_TASK_ALWAYS_EAGER = True