"""
patrimoine/urls.py — URLconf de l'app patrimoine.

Inclus depuis config/urls.py avec : path("patrimoine/", include("patrimoine.urls")).
Toutes les URLs sont préfixées /patrimoine/ et nommées sous le namespace `patrimoine`.
"""

from django.urls import path

from . import views

app_name = "patrimoine"  # namespace → {% url 'patrimoine:asset_class' slug %}

urlpatterns = [
    # /patrimoine/sidebar-toggle/ → persiste l'état du disclosure (POST HTMX, 204)
    # Déclaré AVANT <slug> pour ne pas être capturé comme une classe d'actifs.
    path("sidebar-toggle/", views.sidebar_toggle, name="sidebar_toggle"),
    # /patrimoine/<slug>/ → page d'une classe d'actifs (listing ou SOON)
    path("<slug:slug>/", views.asset_class_page, name="asset_class"),
]
