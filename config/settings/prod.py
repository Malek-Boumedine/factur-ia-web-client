from .base import *
import os

DEBUG = False
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")

# Sécurité accrue en prod
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Ici, on va configurer Redis pour les sessions plus tard