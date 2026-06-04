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

from decouple import config
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import include, path

# URL de l'interface admin Django — lue depuis .env pour ne pas être devinable.
# En local : ADMIN_URL=admin (défaut, pratique)
# En prod  : ADMIN_URL=un-chemin-secret-que-seul-toi-connais (ex: "gestion-b4f2a1")
# Sans cette variable en prod → un attaquant qui essaie /admin/ tombe sur une 404.
# Important : toujours terminer SANS slash — le path() en ajoute un.
ADMIN_URL = config("ADMIN_URL", default="admin")


# Vue health check — utilisée par Railway pour savoir si l'app est vivante.
# Pas de @login_required : Railway pingue cette URL sans cookie de session.
# Pas de DB : si la DB est down, on veut quand même répondre 200 (le container
# est vivant, c'est la DB qui a un problème — Railway ne doit pas redémarrer l'app).
def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


# Vue temporaire de test pour valider le layout Phase 1B.
# Données fictives hardcodées — sera remplacée par une vraie vue avec données
# DB quand la Phase 2 (Finpension, net worth) sera implémentée.
@login_required
def synthese(request):
    return render(request, "synthese/index.html", {})


urlpatterns = [
    # /healthz/ — Railway pingue cette URL toutes les 30s pour vérifier que
    # l'app répond. Si elle ne répond plus, Railway redémarre le container.
    path("healthz/", healthz, name="healthz"),
    path(f"{ADMIN_URL}/", admin.site.urls),
    path("", include("django.contrib.auth.urls")),
    path("synthese/", synthese, name="synthese"),
    # URLs de l'app budget — vues + templates de l'interface Budget
    # Toutes les URLs sont préfixées par /budget/
    path("budget/", include("budget.urls")),
    # URLs de l'app imports — upload et traitement de fichiers bancaires
    path("import/", include("imports.urls")),
    # URLs de l'app patrimoine — navigation par classe d'actifs (Phase 3A)
    path("patrimoine/", include("patrimoine.urls")),
]
