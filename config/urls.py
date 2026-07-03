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
from core.views.abonnements import (
    abonnement_changer_view,
    abonnement_prolonger_view,
    abonnements_view,
    plan_create_view,
    plan_delete_view,
    plan_update_view,
    plans_admin_view,
)
from core.views.admins_plateforme import admins_plateforme_view
from core.views.catalogue import (
    catalogue_create_view,
    catalogue_deactivate_view,
    catalogue_detail_view,
    catalogue_list_view,
    catalogue_reactivate_view,
    catalogue_update_view,
)
from core.views.clients import (
    client_create_view,
    client_deactivate_view,
    client_detail_view,
    client_reactivate_view,
    client_update_view,
    clients_list_view,
)
from core.views.documents import upload_document_view
from core.views.equipe import equipe_view
from core.views.home import home_view
from core.views.profil import profil_view


urlpatterns = [
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
    path("profil/", profil_view, name="profil"),
    path("equipe/", equipe_view, name="equipe"),
    path("admins/", admins_plateforme_view, name="admins_plateforme"),
    path("abonnements/", abonnements_view, name="abonnements"),
    path(
        "abonnements/prolonger/",
        abonnement_prolonger_view,
        name="abonnement_prolonger",
    ),
    path(
        "abonnements/<int:abonnement_id>/choisir/",
        abonnement_changer_view,
        name="abonnement_changer",
    ),
    path("plans/", plans_admin_view, name="plans_admin"),
    path("plans/nouveau/", plan_create_view, name="plan_create"),
    path(
        "plans/<int:abonnement_id>/modifier/",
        plan_update_view,
        name="plan_update",
    ),
    path(
        "plans/<int:abonnement_id>/supprimer/",
        plan_delete_view,
        name="plan_delete",
    ),
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
    path(
        "clients/<int:client_id>/reactiver/",
        client_reactivate_view,
        name="client_reactivate",
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
    path(
        "catalogue/<int:produit_id>/reactiver/",
        catalogue_reactivate_view,
        name="catalogue_reactivate",
    ),
    path("documents/upload/", upload_document_view, name="upload_document"),
    path("", home_view, name="home"),
]
