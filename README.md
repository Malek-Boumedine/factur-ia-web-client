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

## Observabilité (OpenTelemetry / Prometheus / Grafana)

Le client est instrumenté avec OpenTelemetry, sur le même schéma que l'API data (`config/telemetry.py`) : requêtes entrantes (les pages du BFF) et surtout **appels sortants vers l'API data** — latence, taux d'erreur, indisponibilités — qui sont le point fragile d'un BFF sans données propres.

**Tout est désactivé par défaut** : sans variable d'activation, rien ne change en local ni en CI (aucun import du SDK, `/metrics` répond 404).

### Activer

Deux interrupteurs indépendants, à poser dans `.env` ou l'environnement :

| Variable | Défaut | Effet |
| --- | --- | --- |
| `OTEL_METRICS_ENABLED` | `False` | métriques + endpoint `/metrics` (format Prometheus, aucun collector requis) |
| `OTEL_ENABLED` | `False` | traces, exportées en OTLP/HTTP vers un collector (`OTEL_EXPORTER_OTLP_ENDPOINT`, défaut `http://localhost:4318`) |

Optionnel : `OTEL_SERVICE_NAME` (défaut `factur-ia-web`), `OTEL_TRACES_EXPORTER=console` pour vérifier les traces sans collector. Un collector injoignable ne casse jamais l'application : l'export se fait en tâche de fond et échoue en silence.

⚠️ **`/metrics` ne doit jamais être public en production** : réservé au scrape Prometheus (réseau interne, ou protection par ingress).

### Lancer la stack locale (Prometheus + Grafana)

```bash
# 1. le client, avec les métriques activées (ici hors Docker ; en Docker,
#    ajouter OTEL_METRICS_ENABLED=True au .env)
OTEL_METRICS_ENABLED=True uv run python manage.py tailwind runserver 0.0.0.0:8000

# 2. la stack (compose séparé : l'application reste lançable seule)
docker compose -f docker-compose.observability.yml up -d
```

- **Grafana** : <http://localhost:3000> (accès anonyme, tout est provisionné depuis `observability/grafana/` — datasource, dashboard, alertes).
- **Prometheus** : <http://localhost:9090> (scrape de `host.docker.internal:8000` toutes les 15 s).
- Mêmes ports que la stack d'observabilité de l'API data : ne pas lancer les deux en même temps.

Le dashboard **« Factur-IA Web »** montre en moitié haute les pages (débit par route, latence p50/p95/p99, taux 4xx/5xx, requêtes en vol) et en moitié basse la **santé de l'API data vue du client** (débit sortant par statut, latence p95, échecs de connexion, part des appels en erreur).

### Alertes et seuils

Provisionnées dans Grafana (`observability/grafana/provisioning/alerting/alertes.yml`), sans Alertmanager : l'état Normal / Pending / Firing est visible dans **Alerting → Alert rules**. Démonstration : couper l'API data et naviguer dans le client — « API data — appels en erreur » passe en Firing en ~3 minutes.

| Alerte | Seuil | Durée avant Firing |
| --- | --- | --- |
| Pages — taux de 5xx élevé | > 5 % des réponses sur 5 min | 2 min |
| API data — appels en erreur (5xx + échecs de connexion) | > 20 % des appels sur 5 min | 2 min |
| API data — latence p95 dégradée | > 2 s sur 5 min | 2 min |
| Client web hors ligne | cible Prometheus down | 2 min |

Particularité à connaître : l'instrumentation httpx standard n'enregistre **aucune métrique quand la connexion échoue** — le compteur maison `api_data_unavailable_total` (incrémenté par `clients/base_client.py` à chaque échec définitif après rejeux) comble ce trou ; c'est lui qui rend une API data éteinte visible dans le dashboard et les alertes.

### Ce que la télémétrie contient — et surtout pas

Contenu : méthode, route **templatée** (`factures/<int:facture_id>/`, jamais l'ID réel), statut, durée ; hôte et port de l'API data côté sortant. Jamais : en-têtes HTTP (le JWT `Authorization` et `x-entreprise-id` ne sont pas capturés), corps de requêtes/réponses, **query strings** (retirées des spans par les hooks de scrubbing — une recherche SIRENE porte un SIRET en query). `/metrics` et `/static/` sont exclus du tracing.

### Journalisation

Format texte lisible (`horodatage NIVEAU [logger] message`), configuré dans `config/settings/base.py`. Niveau global ajustable par la variable `LOG_LEVEL` (défaut `INFO` ; `WARNING` conseillé en production). Le logger `clients` est le canal dédié aux échanges avec l'API data : rejeux réseau en WARNING, échecs définitifs en ERROR. Les logs de `httpx` sont coupés sous WARNING (ils contiennent l'URL complète, query string incluse).
