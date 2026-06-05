"""
patrimoine/urls.py — URLconf de l'app patrimoine.

Inclus depuis config/urls.py avec : path("patrimoine/", include("patrimoine.urls")).
Toutes les URLs sont préfixées /patrimoine/ et nommées sous le namespace `patrimoine`.
"""

from django.urls import path

from . import views

app_name = "patrimoine"  # namespace → {% url 'patrimoine:asset_class' slug %}

urlpatterns = [
    # /patrimoine/ → page bilan « Patrimoine brut » (cible du clic sur le label)
    path("", views.overview, name="overview"),
    # /patrimoine/sidebar-toggle/ → toggle déplier/replier (POST HTMX → 204)
    # Déclaré AVANT <slug> pour ne pas être capturé comme une classe d'actifs.
    path("sidebar-toggle/", views.sidebar_toggle, name="sidebar_toggle"),
    # /patrimoine/period/<period>/ → change la période du bilan (POST → session, PRG)
    # 2 segments → ne clashe pas avec <slug> (1 segment).
    path("period/<str:period>/", views.set_period, name="set_period"),
    # /patrimoine/filter/class/<slug>/ → coche/décoche une classe (POST → session, PRG).
    # slug="all" → tout cocher.
    path("filter/class/<slug:slug>/", views.toggle_class, name="toggle_class"),
    # /patrimoine/<slug>/ → page d'une classe d'actifs (listing ou SOON)
    path("<slug:slug>/", views.asset_class_page, name="asset_class"),
]
