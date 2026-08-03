# ==============================================================================
# Image locale du client web Factur-IA (Django 6 / Python 3.13).
# Une seule étape suffit : django-tailwind-cli utilise un binaire Tailwind
# autonome, donc pas de Node ni d'étape de build d'assets séparée.
# ==============================================================================

# Image officielle Python, variante légère, alignée sur .python-version.
FROM python:3.13-slim

# uv (gestionnaire de paquets) copié depuis son image officielle.
# Version épinglée pour des builds reproductibles, sans `curl | sh`.
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

# PYTHONUNBUFFERED : les logs Python sortent immédiatement (visibles dans
# `docker compose logs`). UV_PROJECT_ENVIRONMENT : le venv est créé dans
# /opt/venv, HORS de /app, car en dev le projet est monté dans /app depuis
# l'hôte — un venv interne au projet serait masqué par ce montage.
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Dépendances installées avant la copie du code : tant que pyproject.toml et
# uv.lock ne changent pas, le cache Docker réutilise cette couche et évite de
# tout réinstaller à chaque modification du code.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Code de l'application (filtré par .dockerignore : ni .env, ni .venv, ni .git).
COPY . .

# Port du serveur de développement Django.
EXPOSE 8000

# Commande de dev du projet : lance le watcher Tailwind (recompile le CSS quand
# les templates changent) ET le serveur Django avec rechargement à chaud.
# 0.0.0.0 pour que le serveur soit joignable depuis l'extérieur du conteneur.
CMD ["uv", "run", "manage.py", "tailwind", "runserver", "0.0.0.0:8000"]
