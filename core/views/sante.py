"""Sondes de santé pour l'orchestrateur (Cloud Run).

Deux routes sans authentification ni dépendance externe :

- `/health` (vivacité) : répond toujours 200 — « le processus tourne ».
- `/ready` (aptitude) : 200 si la base de sessions répond, 503 sinon. La base
  est la seule dépendance réellement bloquante du BFF : sans elle, aucune
  session, donc aucune page utilisable. L'API data n'est volontairement PAS
  vérifiée ici : sa panne se gère par page d'erreur côté utilisateur, pas en
  retirant l'instance du load balancing (ça ne ferait qu'ajouter une panne).
"""

import logging

from django.db import connection
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)


def health_view(request: HttpRequest) -> JsonResponse:
    """Sonde de vivacité : le processus répond, rien d'autre à prouver."""
    return JsonResponse({"status": "ok"})


def ready_view(request: HttpRequest) -> JsonResponse:
    """Sonde d'aptitude : vérifie que la base de sessions est joignable.

    Un vrai `SELECT 1`, pas `ensure_connection()` : avec les connexions
    persistantes (CONN_MAX_AGE), une connexion déjà ouverte mais morte
    passerait ce dernier sans erreur — seul un aller-retour réel prouve
    que la base répond.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("Sonde /ready : base de sessions injoignable")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
