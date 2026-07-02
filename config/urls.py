"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from core.views.auth import (
    forgot_password_view,
    login_view,
    logout_view,
    onboarding_view,
    profile_lock_view,
    reset_password_view,
    signup_view,
)
from core.views.admins_plateforme import admins_plateforme_view
from core.views.catalogue import (
    catalogue_create_view,
    catalogue_deactivate_view,
    catalogue_detail_view,
    catalogue_list_view,
    catalogue_update_view,
)
from core.views.clients import (
    client_create_view,
    client_deactivate_view,
    client_detail_view,
    client_update_view,
    clients_list_view,
)
from core.views.documents import upload_document_view
from core.views.equipe import equipe_view
from core.views.home import home_view


urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("inscription/", signup_view, name="signup"),
    path("mot-de-passe-oublie/", forgot_password_view, name="forgot_password"),
    path(
        "reinitialiser-mot-de-passe/",
        reset_password_view,
        name="reset_password",
    ),
    path("profile-lock/", profile_lock_view, name="profile_lock"),
    path("onboarding/", onboarding_view, name="onboarding"),
    path("equipe/", equipe_view, name="equipe"),
    path("admins/", admins_plateforme_view, name="admins_plateforme"),
    path("clients/", clients_list_view, name="clients"),
    path("clients/nouveau/", client_create_view, name="client_create"),
    path("clients/<int:client_id>/", client_detail_view, name="client_detail"),
    path(
        "clients/<int:client_id>/modifier/",
        client_update_view,
        name="client_update",
    ),
    path(
        "clients/<int:client_id>/desactiver/",
        client_deactivate_view,
        name="client_deactivate",
    ),
    path("catalogue/", catalogue_list_view, name="catalogue"),
    path("catalogue/nouveau/", catalogue_create_view, name="catalogue_create"),
    path(
        "catalogue/<int:produit_id>/",
        catalogue_detail_view,
        name="catalogue_detail",
    ),
    path(
        "catalogue/<int:produit_id>/modifier/",
        catalogue_update_view,
        name="catalogue_update",
    ),
    path(
        "catalogue/<int:produit_id>/desactiver/",
        catalogue_deactivate_view,
        name="catalogue_deactivate",
    ),
    path("documents/upload/", upload_document_view, name="upload_document"),
    path("", home_view, name="home"),
]
