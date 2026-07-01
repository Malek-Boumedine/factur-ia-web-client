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
    path("documents/upload/", upload_document_view, name="upload_document"),
    path("", home_view, name="home"),
]
