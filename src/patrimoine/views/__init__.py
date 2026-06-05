"""patrimoine/views/ — package de vues (cf. feedback_python_packages : pas de views.py à plat)."""

from .navigation import asset_class_page, sidebar_toggle
from .overview import overview, set_period, toggle_class

__all__ = [
    "asset_class_page",
    "overview",
    "set_period",
    "sidebar_toggle",
    "toggle_class",
]
