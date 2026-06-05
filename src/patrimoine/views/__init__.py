"""patrimoine/views/ — package de vues (cf. feedback_python_packages : pas de views.py à plat)."""

from .asset_class import (
    asset_class_page,
    asset_class_transactions,
    set_asset_class_period,
    set_asset_class_stacked,
    set_asset_class_tab,
)
from .navigation import sidebar_toggle
from .overview import overview, set_period, toggle_class

__all__ = [
    "asset_class_page",
    "asset_class_transactions",
    "overview",
    "set_asset_class_period",
    "set_asset_class_stacked",
    "set_asset_class_tab",
    "set_period",
    "sidebar_toggle",
    "toggle_class",
]
