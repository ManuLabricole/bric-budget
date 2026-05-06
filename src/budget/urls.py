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
    # /budget/panel/rule-create-standalone/ → formulaire création règle sans transaction source (fragment HTMX)
    path(
        "panel/rule-create-standalone/",
        views.budget_panel_rule_create_standalone,
        name="panel_rule_create_standalone",
    ),
    # /budget/panel/rule-standalone-preview/ → aperçu live multi-keywords (GET HTMX)
    path(
        "panel/rule-standalone-preview/",
        views.budget_rule_standalone_preview,
        name="rule_standalone_preview",
    ),
    # /budget/transactions/rule-create-standalone/ → crée N règles + bulk apply (POST)
    path(
        "transactions/rule-create-standalone/",
        views.budget_rule_create_standalone_submit,
        name="rule_create_standalone_submit",
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
    # ── Filtres multi-select (T1 + T2) ──────────────────────────────────────
    # /budget/filter/account/<account_id>/ → toggle compte dans le filtre session
    # account_id=0 → réinitialise (tous les comptes)
    path(
        "filter/account/<int:account_id>/",
        views.budget_toggle_filter_account,
        name="toggle_filter_account",
    ),
    # /budget/filter/category/<slug>/ → toggle catégorie dans le filtre session
    # slug="all" → réinitialise (toutes les catégories)
    path(
        "filter/category/<slug:slug>/",
        views.budget_toggle_filter_category,
        name="toggle_filter_category",
    ),
    # ── Export (T4) ─────────────────────────────────────────────────────────
    # /budget/export/rules/ → télécharge les règles de catégorisation en JSON
    path(
        "export/rules/",
        views.budget_export_rules_download,
        name="export_rules_download",
    ),
    # ── CRUD Règles (Phase 2G) ───────────────────────────────────────────────
    # /budget/panel/rules/ → panel liste des règles (fragment HTMX → #modal-content)
    path("panel/rules/", views.budget_panel_rules_list, name="panel_rules_list"),
    # /budget/rules/<id>/toggle/ → inverse is_active, retourne la ligne (POST HTMX)
    path(
        "rules/<int:rule_id>/toggle/",
        views.budget_rule_toggle_active,
        name="rule_toggle_active",
    ),
    # /budget/rules/<id>/delete/ → supprime la règle, retourne vide (POST HTMX)
    path(
        "rules/<int:rule_id>/delete/",
        views.budget_rule_delete,
        name="rule_delete",
    ),
    # /budget/rules/<id>/edit/ → GET = formulaire édition, POST = sauvegarde
    path(
        "rules/<int:rule_id>/edit/",
        views.budget_rule_row_edit,
        name="rule_row_edit",
    ),
    path(
        "rules/<int:rule_id>/edit/submit/",
        views.budget_rule_edit_submit,
        name="rule_edit_submit",
    ),
]
