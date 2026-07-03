"""Constantes métier partagées entre formulaires et vues.

Valeurs issues du contrat OpenAPI : les clés sont les valeurs d'enums envoyées
à l'API (ne jamais les traduire), les libellés sont l'affichage FR.
"""

# Enum métier TypeProduit du contrat OpenAPI.
TYPES_PRODUIT = [
    ("produit", "Produit"),
    ("prestation", "Prestation"),
    ("service", "Service"),
]
TYPES_PRODUIT_VALUES = {value for value, _ in TYPES_PRODUIT}
