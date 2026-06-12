"""patrimoine/views/ — package de vues (cf. feedback_python_packages : pas de views.py à plat)."""

from .account_wizard import account_create, account_form
from .asset_class import (
    asset_class_page,
    asset_class_transactions,
    set_asset_class_period,
    set_asset_class_stacked,
    set_asset_class_tab,
)
from .institutions import (
    institution_logo_form,
    institution_logo_repair,
    institution_picker,
)
from .navigation import sidebar_toggle
from .overview import overview, set_period, toggle_class

__all__ = [
    "account_create",
    "account_form",
    "asset_class_page",
    "asset_class_transactions",
    "institution_logo_form",
    "institution_logo_repair",
    "institution_picker",
    "overview",
    "set_asset_class_period",
    "set_asset_class_stacked",
    "set_asset_class_tab",
    "set_period",
    "sidebar_toggle",
    "toggle_class",
]
