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
    # /budget/panel/transactions/ → partial HTMX — liste transactions dans le right panel
    # Chargé par le bouton "Tout voir" via hx-get. Retourne uniquement le fragment HTML.
    path(
        "panel/transactions/",
        views.budget_panel_transactions,
        name="panel_transactions",
    ),
    # /budget/panel/transactions/<action>/ → met à jour la période puis retourne le fragment
    # action : "prev" | "next" | "1m" | "3m" | "1y"
    path(
        "panel/transactions/<str:action>/",
        views.budget_panel_navigate,
        name="panel_navigate",
    ),
    # /budget/transactions/<tx_id>/toggle-ignore/ → bascule is_ignored + retourne fragment ligne
    # POST uniquement (mutation DB) — HTMX swap="outerHTML" sur #tx-<id>
    path(
        "transactions/<int:tx_id>/toggle-ignore/",
        views.budget_toggle_ignore,
        name="toggle_ignore",
    ),
    # /budget/panel/category-picker/?tx_id=X → picker catégorie (fragment HTMX)
    # GET — lecture seule, retourne _panel_category_picker.html dans #panel-content
    path(
        "panel/category-picker/",
        views.budget_panel_category_picker,
        name="panel_category_picker",
    ),
    # /budget/transactions/categorize/ → assigne category + subcategory sur une transaction
    # POST — mutation DB, retourne _panel_tx_list.html + header HX-Trigger pour le toast
    path(
        "transactions/categorize/",
        views.budget_categorize_transaction,
        name="categorize",
    ),
]
