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
    # /patrimoine/<slug>/period/<period>/ → change la période de la courbe (POST)
    path(
        "<slug:slug>/period/<str:period>/",
        views.set_asset_class_period,
        name="set_asset_class_period",
    ),
    # /patrimoine/<slug>/stacked/ → bascule mode standard/empilé (POST)
    path(
        "<slug:slug>/stacked/",
        views.set_asset_class_stacked,
        name="set_asset_class_stacked",
    ),
    # /patrimoine/<slug>/tab/<tab>/ → bascule onglet comptes/transactions (GET)
    path(
        "<slug:slug>/tab/<str:tab>/",
        views.set_asset_class_tab,
        name="set_asset_class_tab",
    ),
    # /patrimoine/<slug>/transactions/ → scroll infini page 2+ (GET, HTMX)
    path(
        "<slug:slug>/transactions/",
        views.asset_class_transactions,
        name="asset_class_transactions",
    ),
    # /patrimoine/institutions/picker/ → catalogue institutions (panel droit, recherche live).
    # 2 segments → ne clashe pas avec <slug> (1 segment), mais déclaré AVANT par prudence.
    path(
        "institutions/picker/",
        views.institution_picker,
        name="institution_picker",
    ),
    # /patrimoine/institutions/<slug>/logo/form/ → formulaire de réparation logo (GET, HTMX #128)
    path(
        "institutions/<slug:slug>/logo/form/",
        views.institution_logo_form,
        name="institution_logo_form",
    ),
    # /patrimoine/institutions/<slug>/logo/ → installe le logo collé à la main (POST, HTMX #128)
    path(
        "institutions/<slug:slug>/logo/",
        views.institution_logo_repair,
        name="institution_logo_repair",
    ),
    # /patrimoine/comptes/nouveau/ → wizard #73 step 2 (formulaire, panel droit, GET)
    path("comptes/nouveau/", views.account_form, name="account_form"),
    # /patrimoine/comptes/creer/ → wizard #73 création (POST → 204 + HX-Redirect)
    path("comptes/creer/", views.account_create, name="account_create"),
    # ── Page zoom compte (#82 PR C) ─────────────────────────────────────────
    # Préfixe "compte/" (2+ segments) → ne clashe pas avec <slug> (1 segment).
    # /patrimoine/compte/<id>/ → page zoom d'un compte (graphe + tx + détails)
    path("compte/<int:account_id>/", views.account_detail, name="account_detail"),
    # /patrimoine/compte/<id>/period/<period>/ → change la période de la courbe (POST)
    path(
        "compte/<int:account_id>/period/<str:period>/",
        views.set_account_period,
        name="set_account_period",
    ),
    # /patrimoine/compte/<id>/transactions/ → scroll infini page 2+ (GET, HTMX)
    path(
        "compte/<int:account_id>/transactions/",
        views.account_transactions,
        name="account_transactions",
    ),
    # /patrimoine/compte/<id>/modifier/ → carte Détails → formulaire d'édition (GET, HTMX, #292)
    path(
        "compte/<int:account_id>/modifier/",
        views.account_edit_form,
        name="account_edit_form",
    ),
    # /patrimoine/compte/<id>/enregistrer/ → valide + persiste l'édition (POST, HTMX, #292)
    path(
        "compte/<int:account_id>/enregistrer/",
        views.account_update,
        name="account_update",
    ),
    # /patrimoine/compte/<id>/archiver/ → soft-delete (POST, HTMX → 204 + HX-Redirect, #292)
    path(
        "compte/<int:account_id>/archiver/",
        views.account_archive,
        name="account_archive",
    ),
    # /patrimoine/compte/<id>/champ/<field>/edit/ → passe un champ en édition (GET, HTMX)
    path(
        "compte/<int:account_id>/champ/<str:field>/edit/",
        views.account_field_form,
        name="account_field_form",
    ),
    # /patrimoine/compte/<id>/champ/<field>/ → valide + persiste le champ (POST, HTMX)
    path(
        "compte/<int:account_id>/champ/<str:field>/",
        views.account_field_save,
        name="account_field_save",
    ),
    # /patrimoine/<slug>/ → page d'une classe d'actifs (listing ou SOON)
    path("<slug:slug>/", views.asset_class_page, name="asset_class"),
]
