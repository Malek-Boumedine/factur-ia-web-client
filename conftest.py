"""Configuration pytest à la racine du projet.

pytest-django n'a pas de wiring dans `pyproject.toml` : il faut lui indiquer le
module de settings à charger. On réutilise la même convention que
`manage.py`/`wsgi.py` — le settings est dérivé de la variable d'environnement
`DJANGO_ENV` (ex. `DJANGO_ENV=test` -> `config.settings.test`).

Sans cela, les tests intégrés à Django (client de test, accès base) sont
ignorés (« no Django settings »).
"""

import os

import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", f"config.settings.{os.getenv('DJANGO_ENV', 'dev')}"
)

# pytest-django lit `DJANGO_SETTINGS_MODULE` avant l'import de ce conftest ;
# on force donc explicitement le chargement des apps ici (idempotent).
django.setup()
