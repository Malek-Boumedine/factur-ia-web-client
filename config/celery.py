import os
from celery import Celery
from dotenv import load_dotenv


load_dotenv()

env = os.getenv("DJANGO_ENV", "dev")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{env}")

# instancie l'application Celery
app = Celery("factur_ia")

# Charge la configuration depuis les settings Django (toutes les variables commenceront par CELERY_)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Demande à Celery de chercher automatiquement des tâches dans tes futures applications (apps/)
app.autodiscover_tasks()
