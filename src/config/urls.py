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
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import include, path


# Vue temporaire de test pour valider le layout Phase 1B.
# Données fictives hardcodées — sera remplacée par une vraie vue avec données
# DB quand la Phase 2 (Finpension, net worth) sera implémentée.
@login_required
def synthese(request):
    return render(request, "synthese/index.html", {})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("django.contrib.auth.urls")),
    path("synthese/", synthese, name="synthese"),
    # Délégation des URLs de l'app transactions à transactions/urls.py
    # Toutes les URLs de l'app sont préfixées par /transactions/
    path("budget/", include("transactions.urls")),
]
