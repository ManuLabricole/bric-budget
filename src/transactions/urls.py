# transactions/urls.py
#
# URLconf de l'application transactions.
# Ce fichier est inclus depuis config/urls.py avec :
#   path("transactions/", include("transactions.urls"))
#
# Principe Django : chaque app gère ses propres URLs dans son urls.py.
# config/urls.py est le "routeur principal" — il délègue aux apps.
# Ici, on ne définit qu'une seule URL pour l'instant : la liste des transactions.

from django.urls import path

from . import views  # importe views.py du même package (transactions/)

app_name = "transactions"  # namespace — permet {% url 'transactions:list' %} dans les templates
# sans risque de collision avec d'autres apps qui auraient une URL "list"

urlpatterns = [
    # /budget/ → page Budget principale
    path("", views.transaction_list, name="list"),
    # /budget/period/<action>/ → navigation temporelle (GET → redirect vers /budget/)
    # action : "prev" | "next" | "1m" | "3m" | "1y"
    # Principe : on lit l'action, on met à jour la session, on redirige.
    # GET (pas POST) car c'est une navigation sans effet de bord sur les données.
    path("period/<str:action>/", views.budget_set_period, name="set_period"),
    # /budget/tab/<tab>/ → bascule l'onglet actif (GET → redirect vers /budget/)
    # tab : "sorties" | "entrees" | "recurrentes"
    path("tab/<str:tab>/", views.budget_set_tab, name="set_tab"),
]
