# factur-ia-web-client

Client web de **Factur-IA**, solution de dématérialisation de factures : dépôt d'un document, extraction automatique par reconnaissance optique, relecture et validation par l'utilisateur, génération au format **Factur-X** et transmission à **Chorus Pro**.

Application **Django 6 / Python 3.13** en rendu serveur, construite comme un **BFF** (Backend-For-Frontend) : elle ne stocke aucune donnée métier, authentifie l'utilisateur auprès de l'API data, garde le jeton en session côté serveur et relaie tous les appels.

## Architecture

| Service | Rôle | Dépôt |
|---|---|---|
| **Client web** (ce dépôt) | Interface, sessions, relais authentifié | `factur-ia-web-client` |
| **API data** | Données métier, règles de gestion, intégrations externes | `factur-ia-api-data` |
| **API IA** | Extraction des documents, asynchrone | `factur-ia-api-ia` |

Le navigateur ne parle **qu'au client web**. Le client ne parle **qu'à l'API data**. Les services externes ne sont joignables que par elle.

Trois raisons à ce découpage :

**Sécurité** — le jeton d'authentification ne transite jamais par le navigateur. Il vit en session côté serveur, injecté à chaque appel. Le navigateur ne détient qu'un identifiant de session opaque.

**Un seul point d'entrée aux données** — personne ne parle à la base ni aux services externes sauf l'API data, qui porte les règles métier.

**Indépendance de l'extraction** — coûteuse et asynchrone, elle évolue sans toucher au reste.

Côté code, tout appel sortant passe par `BaseAPIClient` (`clients/base_client.py`), qui injecte les en-têtes d'authentification, applique délais d'attente et rejeux, et traduit les erreurs HTTP en exceptions métier.

### Sessions

En **développement** : cache Redis. En **production** : base de données. Dans les deux cas côté serveur — les cookies signés sont exclus, le jeton y serait lisible depuis le navigateur.

### Authentification

**Connexion** par flux OAuth2, le jeton retourné étant stocké en session. Un en-tête d'entreprise détermine le locataire à chaque appel, l'isolation étant appliquée par l'API data.

**Expiration détectée deux fois** : en amont, un intergiciel purge la session dès que le jeton est expiré ; en aval, tout refus de l'API vide la session et redirige vers la connexion.

## Installation

```bash
git clone github.com/Malek-Boumedine/factur-ia-web-client && cd factur-ia-web-client

uv sync --all-groups          # dépendances, groupes de dev inclus
cp .env.example .env          # renseigner SECRET_KEY et API_DATA_URL
docker compose up -d redis    # sessions en développement
```

Aucune migration à exécuter en local : le client n'a **aucun modèle de données propre**. Pas de compte à créer non plus — les utilisateurs sont ceux de l'API data.

**Prérequis** : Python 3.13, [uv](https://docs.astral.sh/uv/), Docker, et l'API data accessible (par défaut sur `http://127.0.0.1:8080`).

## Lancement

```bash
uv run python manage.py tailwind runserver   # serveur de dev + compilation CSS
```

Application sur <http://localhost:8000>.

Avec Docker : `docker compose up --build`. L'API data doit alors écouter sur `0.0.0.0:8080` pour être joignable depuis les conteneurs.

## Commandes utiles

| Commande | Rôle |
|---|---|
| `uv run python manage.py tailwind runserver` | Serveur de dev |
| `DJANGO_ENV=test uv run pytest` | Tests |
| `DJANGO_ENV=test uv run pytest --cov=.` | Tests avec couverture |
| `uv run ruff check .` / `uv run ruff format .` | Lint et formatage |
| `uv run mypy .` | Vérification de types |
| `uv run pre-commit run --all-files` | Portail qualité complet |

**`DJANGO_ENV=test` est obligatoire** pour les tests : sans cette variable, ils tournent sur les réglages de développement.

## Variables d'environnement

Toutes lues depuis `.env` — modèle dans `.env.example`, le fichier réel n'est jamais commité.

| Variable | Rôle | Défaut |
|---|---|---|
| `SECRET_KEY` | Clé secrète Django | — **obligatoire** |
| `API_DATA_URL` | URL de l'API data | — **obligatoire** |
| `DJANGO_ENV` | Réglages chargés : `dev`, `test` ou `prod` | `dev` |
| `DEBUG` | Mode débogage (forcé à `False` en production) | `True` |
| `ALLOWED_HOSTS` | Hôtes autorisés | `localhost,127.0.0.1` |
| `API_CONNECT_TIMEOUT` | Délai de connexion vers l'API (s) | `5.0` |
| `API_READ_TIMEOUT` | Délai de lecture (s) | `15.0` |
| `API_MAX_RETRIES` | Rejeux au-delà de la tentative initiale | `2` |
| `API_IAM_AUTH_ENABLED` | Jeton d'identité de plateforme (production) | `False` |
| `DOCUMENT_UPLOAD_MAX_SIZE` | Taille maximale d'un dépôt (octets) | `10485760` |
| `OTEL_METRICS_ENABLED` | Métriques et route `/metrics` | `False` |
| `OTEL_ENABLED` | Traces OpenTelemetry | `False` |
| `LOG_LEVEL` | Niveau de journalisation | `INFO` |

En production s'ajoutent `CSRF_TRUSTED_ORIGINS` et les variables de base de données, injectées par l'infrastructure.

## Tests

**tests** répartis entre `core/tests/` (vues, formulaires, gardes d'accès, intergiciel) et `clients/tests/` (socle HTTP : en-têtes, traduction des erreurs, politique de rejeu).

Les tests ne dépendent d'aucun service externe ni d'aucun fichier de configuration local : l'API est simulée au niveau des clients, les sessions passent en mémoire, et les réglages de test figent tout ce que la configuration lit habituellement dans l'environnement.

## Observabilité

Le client est instrumenté avec OpenTelemetry : requêtes entrantes, et surtout **appels sortants vers l'API data** — latence, taux d'erreur, indisponibilités, qui sont le point fragile d'un BFF sans données propres.

**Tout est désactivé par défaut.** Deux interrupteurs indépendants : `OTEL_METRICS_ENABLED` pour les métriques et la route `/metrics`, `OTEL_ENABLED` pour les traces. Un collecteur injoignable ne casse jamais l'application.

Une particularité à connaître : l'instrumentation HTTP standard n'enregistre **aucune métrique quand la connexion échoue**. Un compteur maison comble ce trou — c'est lui qui rend une API éteinte visible dans les tableaux de bord.

**Ce que la télémétrie contient** : méthode, route modélisée (jamais l'identifiant réel), statut, durée. **Jamais** : en-têtes, corps de requêtes, ni paramètres d'URL — une recherche d'entreprise en porte un identifiant.

La stack de visualisation (Prometheus, Grafana, tableaux de bord, alertes) vit dans le dépôt [`factur-ia-infra`](https://github.com/Malek-Boumedine/factur-ia-infra).

## Contrat et versionnement

**Contrat OpenAPI** : ce client consomme le schéma exporté par l'API data, versionné dans `contracts/openapi.json` et jamais édité à la main. Régénération : voir `docs/openapi-client-setup.md`.

**Versionnement** automatisé à partir des messages de commit, historique dans `CHANGELOG.md`.

## Livraison continue

À la publication d'une version, le workflow récupère le tag correspondant, construit l'image de production depuis `Dockerfile.prod` (jamais celle de développement), la pousse avec deux étiquettes — version et empreinte du commit, pas de `latest` —, exécute le job de migration, déploie la nouvelle révision par empreinte, puis vérifie la sonde de santé. Un déclenchement manuel permet de redéployer n'importe quelle version, retour arrière compris.

**Partage des responsabilités** : l'infrastructure possède la *forme* du service — configuration, secrets, dimensionnement — et ignore le champ image ; la livraison possède son *contenu*. Elle ne touche jamais à l'infrastructure.

### Variables GitHub

Aucun secret : la fédération d'identité rend tout stockage confidentiel inutile. Tout va dans les **variables de dépôt**.

| Variable | Contenu |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Fournisseur d'identité, sortie Terraform |
| `GCP_DEPLOY_SA` | `github-deployer-web@<projet>.iam.gserviceaccount.com` |
| `GCP_PROJECT_ID` | Identifiant du projet |
| `GCP_REGION` | `europe-west9` |
| `ARTIFACT_REGISTRY_REPO` | `factur-ia` |
| `CLOUD_RUN_SERVICE` | `factur-ia-web` |
| `CLOUD_RUN_MIGRATE_JOB` | `factur-ia-migrate-web` |

Les ressources correspondantes — compte de déploiement, rôles, liaison d'identité — sont décrites dans le dépôt d'infrastructure.

---

Conventions de contribution (commits, langue, flux Git) : voir `CLAUDE.md`.
