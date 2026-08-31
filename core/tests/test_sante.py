"""Tests des sondes de santé (`/health`, `/ready`).

Contrat attendu par Cloud Run : `/health` répond toujours 200 ; `/ready`
répond 200 si la base de sessions est joignable, 503 sinon — et ne consulte
jamais l'API data (sa panne ne doit pas sortir l'instance du load balancing).
"""

from unittest.mock import patch

from django.test import Client
from django.urls import reverse

import pytest


def test_health_repond_toujours_ok(client: Client) -> None:
    """`/health` répond 200 sans condition, sans session ni base."""
    response = client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_ok_quand_la_base_repond(client: Client) -> None:
    """`/ready` répond 200 quand la connexion base s'établit."""
    response = client.get(reverse("ready"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_503_quand_la_base_est_injoignable(client: Client) -> None:
    """`/ready` répond 503 si la connexion base échoue, sans lever d'erreur."""
    with patch(
        "core.views.sante.connection.cursor",
        side_effect=OSError("base injoignable"),
    ):
        response = client.get(reverse("ready"))
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
