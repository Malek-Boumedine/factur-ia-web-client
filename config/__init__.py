# Cela garantit que l'application Celery est toujours importée quand Django démarre
from .celery import app as celery_app

__all__ = ("celery_app",)
