# ruff: noqa: F401
"""
budget/views/ — Package des vues de l'application Budget.

Re-exporte toutes les vues publiques pour que urls.py puisse faire
`from . import views` et accéder à `views.budget_index` etc. sans changer.

Sous-modules :
    core         → budget_index, navigation temporelle, onglets, filtres, toggle_decimals
    transactions → panneau transactions, catégorisation, objectifs
    rules        → wizard règles, CRUD règles, export
    categories   → détail catégorie, gestion CRUD catégories
"""

from .categories import (
    budget_category_cashflow_fragment,
    budget_category_create_submit,
    budget_category_delete,
    budget_category_detail,
    budget_category_tx_fragment,
    budget_panel_category_create,
    budget_panel_category_delete_confirm,
    budget_panel_category_manage,
    budget_panel_category_manage_detail,
)
from .core import (
    budget_index,
    budget_set_cat_tab,
    budget_set_period,
    budget_set_period_month,
    budget_set_tab,
    budget_toggle_decimals,
    budget_toggle_filter_account,
    budget_toggle_filter_category,
)
from .rules import (
    budget_export_rules_download,
    budget_modal_rule_intro,
    budget_panel_rule_create,
    budget_panel_rule_create_standalone,
    budget_panel_rules_list,
    budget_rule_create_standalone_submit,
    budget_rule_create_submit,
    budget_rule_delete,
    budget_rule_edit_submit,
    budget_rule_live_preview,
    budget_rule_preview,
    budget_rule_row_edit,
    budget_rule_standalone_preview,
    budget_rule_toggle_active,
)
from .transactions import (
    budget_categorize_transaction,
    budget_modal_target_create,
    budget_panel_category_picker,
    budget_panel_navigate,
    budget_panel_transactions,
    budget_panel_tx_detail,
    budget_toggle_ignore,
    budget_toggle_reconcile,
)
