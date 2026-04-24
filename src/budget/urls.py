# budget/urls.py
#
# URLconf de l'application budget.
# Inclus depuis config/urls.py avec : path("budget/", include("budget.urls"))
#
# Toutes les URLs de l'UI Budget sont ici.
# Les modèles et services restent dans transactions/ — budget/ ne fait que les afficher.

from django.urls import path

from . import views

app_name = "budget"  # namespace — permet {% url 'budget:index' %} dans les templates

urlpatterns = [
    # /budget/ → page Budget principale
    path("", views.budget_index, name="index"),
    # /budget/period/<action>/ → navigation temporelle (GET → redirect vers /budget/)
    # action : "prev" | "next" | "1m" | "3m" | "1y"
    path("period/<str:action>/", views.budget_set_period, name="set_period"),
    # /budget/period/month/<year>/<month>/ → saute vers un mois absolu (bar chart objectif)
    path(
        "period/month/<int:year>/<int:month>/",
        views.budget_set_period_month,
        name="set_period_month",
    ),
    # /budget/tab/<tab>/ → bascule l'onglet actif (GET → redirect vers /budget/)
    # tab : "sorties" | "entrees" | "recurrentes"
    path("tab/<str:tab>/", views.budget_set_tab, name="set_tab"),
    # /budget/panel/transactions/ → partial HTMX — liste transactions dans le right panel
    path(
        "panel/transactions/",
        views.budget_panel_transactions,
        name="panel_transactions",
    ),
    # /budget/panel/transactions/<action>/ → met à jour la période puis retourne le fragment
    path(
        "panel/transactions/<str:action>/",
        views.budget_panel_navigate,
        name="panel_navigate",
    ),
    # /budget/transactions/<tx_id>/toggle-ignore/ → bascule is_ignored (POST HTMX)
    path(
        "transactions/<int:tx_id>/toggle-ignore/",
        views.budget_toggle_ignore,
        name="toggle_ignore",
    ),
    # /budget/panel/category-picker/?tx_id=X → picker catégorie (fragment HTMX)
    path(
        "panel/category-picker/",
        views.budget_panel_category_picker,
        name="panel_category_picker",
    ),
    # /budget/transactions/categorize/ → assigne category + subcategory (POST HTMX)
    path(
        "transactions/categorize/",
        views.budget_categorize_transaction,
        name="categorize",
    ),
    # /budget/panel/tx-detail/?tx_id=X → détail d'une transaction (fragment HTMX)
    path("panel/tx-detail/", views.budget_panel_tx_detail, name="panel_tx_detail"),
    # /budget/transactions/<tx_id>/toggle-reconcile/ → bascule is_reconciled (POST HTMX)
    path(
        "transactions/<int:tx_id>/toggle-reconcile/",
        views.budget_toggle_reconcile,
        name="toggle_reconcile",
    ),
    # /budget/panel/rule-create/?tx_id=X&keyword=MIGROS → formulaire création règle (fragment HTMX)
    path(
        "panel/rule-create/", views.budget_panel_rule_create, name="panel_rule_create"
    ),
    # /budget/transactions/rule-preview/ → prévisualise l'impact d'une règle (POST)
    path("transactions/rule-preview/", views.budget_rule_preview, name="rule_preview"),
    # /budget/transactions/rule-live-preview/ → aperçu live des transactions matchées (GET HTMX)
    path(
        "transactions/rule-live-preview/",
        views.budget_rule_live_preview,
        name="rule_live_preview",
    ),
    # /budget/transactions/rule-create/ → crée la règle + bulk apply (POST)
    path(
        "transactions/rule-create/",
        views.budget_rule_create_submit,
        name="rule_create_submit",
    ),
    # /budget/modal/target-create/ → modal création / modification d'un objectif mensuel
    path(
        "modal/target-create/",
        views.budget_modal_target_create,
        name="modal_target_create",
    ),
    # /budget/modal/rule-intro/ → modal step 1 wizard règle : confirmation avant keyword selection
    path(
        "modal/rule-intro/",
        views.budget_modal_rule_intro,
        name="modal_rule_intro",
    ),
    # /budget/categorie/tab/<tab>/ → bascule l'onglet actif de la page catégorie
    # tab : "transactions" | "subcategories" | "objectif"
    # Doit être AVANT categorie/<slug>/ pour éviter que "tab" soit interprété comme un slug.
    path(
        "categorie/tab/<str:tab>/",
        views.budget_set_cat_tab,
        name="set_cat_tab",
    ),
    # /budget/categorie/<slug>/ → page détail d'une catégorie (Sankey sous-catégories + transactions)
    path(
        "categorie/<slug:slug>/", views.budget_category_detail, name="category_detail"
    ),
]
