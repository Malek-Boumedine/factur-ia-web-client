# Génération du client typé Django depuis l'OpenAPI (niveau 2)

## 1. Côté repo API (factur-ia-data)

- Placer `export_openapi.py` dans `scripts/`
- L'ajouter à votre routine de dev, par exemple dans le README ou un Makefile :

```bash
uv run python scripts/export_openapi.py
```

- Committer `contracts/openapi.json` à chaque modification de routes/schémas.

## 2. Transférer le contrat vers le repo Django

Le plus simple pour le MVP : copier le fichier `contracts/openapi.json` du repo API
vers le même chemin dans le repo Django (`contracts/openapi.json`), et le committer
aussi de ce côté. Un script bash suffit si les deux repos sont en local côte à côte :

```bash
cp ../factur-ia-data/contracts/openapi.json ./contracts/openapi.json
```

(Pas besoin de submodule Git ou de package partagé pour un MVP solo — ça ajouterait
de la complexité sans bénéfice à ce stade. Si le projet grossit après le diplôme,
publier le contrat sur un registre interne ou via CI sera la suite logique.)

## 3. Installer le générateur côté Django

```bash
uv add --dev openapi-python-client
```

## 4. Générer le client

```bash
uv run openapi-python-client generate \
  --path contracts/openapi.json \
  --output-path clients/generated \
  --overwrite
```

Cela crée `clients/generated/` avec, pour chaque tag/route de votre API, des
fonctions Python typées (modèles Pydantic inclus) — par exemple
`clients/generated/api/factures/create_facture.py`. Ne touchez jamais ce dossier
à la main, il sera régénéré à chaque appel de la commande.

## 5. Câbler le client généré avec votre JWT existant

Le client généré attend un `httpx.Client` (ou `AsyncClient`) configuré. Vous
réutilisez exactement le mécanisme d'injection JWT que vous avez déjà construit
en Epic 2, vous ne le dupliquez pas :

```python
# clients/api_data_client.py
from clients.generated import AuthenticatedClient
from django.conf import settings


def get_api_data_client(request) -> AuthenticatedClient:
    """
    Construit le client typé pour la requête en cours, avec le JWT
    de session injecté (même logique que votre client centralisé actuel)
    et le header multi-tenant x-entreprise-id.
    """
    jwt_token = request.session.get("api_jwt")  # adapter selon votre implémentation actuelle
    entreprise_id = request.session.get("entreprise_id")

    return AuthenticatedClient(
        base_url=settings.API_DATA_URL,
        token=jwt_token,
        headers={"x-entreprise-id": str(entreprise_id)},
        timeout=10.0,
    )
```

Puis dans une vue :

```python
from clients.generated.api.factures import create_facture
from clients.generated.models import FactureCreate

def creer_facture_view(request):
    client = get_api_data_client(request)
    payload = FactureCreate(client_id=..., lignes=[...])
    response = create_facture.sync(client=client, body=payload)
    # response est déjà typé — mypy vous signale immédiatement
    # si un champ attendu par l'API n'existe plus côté Django
    ...
```

## 6. Routine à prendre dès maintenant

À chaque fois que vous modifiez une route ou un schéma côté API :

```bash
# dans factur-ia-data
uv run python scripts/export_openapi.py

# dans factur-ia-web-django
cp ../factur-ia-data/contracts/openapi.json ./contracts/openapi.json
uv run openapi-python-client generate --path contracts/openapi.json --output-path clients/generated --overwrite
```

Si vous voulez automatiser ça plus tard (niveau 3, post-MVP), une étape CI qui
échoue si `contracts/openapi.json` n'est pas synchronisé avec le code de l'API
ferme la boucle — mais pour les 5 semaines qui viennent, le faire manuellement à
chaque changement de contrat suffit largement et coûte 30 secondes.
