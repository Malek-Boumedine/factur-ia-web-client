"""Filtres de template pour la navigation (état actif de la sidebar)."""

from django import template

register = template.Library()


@register.filter
def in_list(value: str | None, names: str) -> bool:
    """Teste l'appartenance exacte de value à une liste de noms séparés par des espaces.

    Contrairement à `{% if value in "a b c" %}` (test de sous-chaîne), le test
    porte sur les mots entiers : `"a" | in_list:"ab abc"` vaut False.
    """
    return value in names.split()
