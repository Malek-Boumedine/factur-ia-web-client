from django.shortcuts import render


def home_view(request):
    """Affiche la page d'accueil (vitrine publique).

    Page marketing accessible à tous ; l'en-tête adapte ses liens selon l'état
    d'authentification stocké en session. Aucune donnée métier n'est chargée.
    """
    return render(request, "core/home.html")
