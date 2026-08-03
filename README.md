# factur-ia-web-client

Client web de Factur-IA : application Django 6 (Python 3.13) servant d'interface utilisateur. C'est un BFF (Backend-For-Frontend) : il ne stocke aucune donnée métier et relaie tous les appels vers l'API data.

## Lancer en local avec Docker

### Prérequis

- Docker et Docker Compose.
- Un fichier `.env` à la racine du projet (voir les variables ci-dessous).
- L'API data lancée sur l'hôte, **en écoute sur `0.0.0.0:8080`** (et pas seulement `127.0.0.1`) : les conteneurs la joignent via `host.docker.internal`, qui ne fonctionne que si l'API accepte les connexions venant d'une autre interface que la boucle locale.

### Démarrage

```bash
docker compose up --build
```

L'application est disponible sur <http://localhost:8000>.

### Les services

- **web** — le client Django, lancé avec `manage.py tailwind runserver` : serveur de développement avec rechargement à chaud + watcher Tailwind qui recompile le CSS quand les templates changent. Le projet est monté dans le conteneur, donc toute modification locale est prise en compte immédiatement.
- **worker** — le worker Celery qui exécute les tâches asynchrones (même image que `web`, seule la commande change).
- **redis** — sessions Django (backend cache) et broker/backend de résultats Celery. Son port est publié sur l'hôte pour pouvoir aussi lancer l'app hors Docker.

Il n'y a volontairement ni base de données (le client n'en a pas), ni reverse proxy, ni observabilité (elle vit dans le compose de l'API data).

### Variables d'environnement

Lues depuis `.env` (jamais copiées dans l'image) :

| Variable | Rôle |
| --- | --- |
| `DJANGO_ENV` | Settings à charger (`dev` en local) |
| `SECRET_KEY` | Clé secrète Django (`openssl rand -hex 32`) |
| `DEBUG` | Mode debug (`True` en local) |
| `ALLOWED_HOSTS` | Hôtes autorisés (`localhost,127.0.0.1`) |
| `API_DATA_URL` | URL de l'API data |
| `CELERY_BROKER_URL` | URL Redis du broker Celery |
| `CELERY_RESULT_BACKEND` | URL Redis des résultats Celery |

Dans les conteneurs, le compose **surcharge** trois d'entre elles :
`CELERY_BROKER_URL` et `CELERY_RESULT_BACKEND` pointent vers le service `redis`, et `API_DATA_URL` vers `http://host.docker.internal:8080` (l'API sur l'hôte). Le `.env` garde ses valeurs `localhost` pour l'usage hors Docker.

### Note sur le binaire Tailwind

`django-tailwind-cli` télécharge un binaire Tailwind autonome (pas de Node) au premier lancement, dans `static/css/tailwind/` — dossier monté depuis l'hôte, donc téléchargé une seule fois et partagé avec le workflow hors Docker. Si le téléchargement a échoué (pas de réseau au premier démarrage), le CSS déjà compilé et versionné (`static/css/tailwind.css`) prend le relais ; relancer simplement le service une fois le réseau revenu pour récupérer le binaire :

```bash
docker compose restart web
```
