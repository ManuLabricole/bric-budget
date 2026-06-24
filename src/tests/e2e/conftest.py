"""
tests/e2e/conftest.py — Fixtures LOCALES aux tests end-to-end navigateur (#159).

Pourquoi un conftest dédié ici, et pas les 5 conftests partagés ?
----------------------------------------------------------------
Les tests E2E ont un cycle de vie différent du reste de la suite :
  - ils tournent dans un VRAI navigateur (Playwright) contre un VRAI serveur
    Django (`live_server`), donc en accès DB *transactionnel* (les deux threads
    ne partagent pas de transaction — les données doivent être committées pour
    que le serveur les voie) ;
  - ils sont *opt-in* via le marker `e2e` (voir pyproject.toml : `-m "not e2e"`
    dans addopts) → ils ne tournent jamais dans la suite pre-push / le job CI
    principal, qui n'installe pas de navigateur.

Ce fichier ne touche AUCUN des 5 conftests partagés (#194) et ne dépend pas des
factories (#194 pas encore mergées) : les données sont créées via l'ORM direct.

Le marker `e2e` est appliqué AUTOMATIQUEMENT à tous les tests de ce paquet
(`pytest_collection_modifyitems`) → pas besoin de décorer chaque test à la main.
"""

import os
import secrets

import pytest

# ── Garde async ↔ ORM sync (pytest-playwright + pytest-django) ───────────────
# pytest-playwright installe une boucle asyncio pour piloter le navigateur. La
# création/setup de la base par pytest-django (`transactional_db`) fait des appels
# ORM SYNCHRONES ; Django les refuse s'il détecte une boucle asyncio active dans le
# thread (SynchronousOnlyOperation). Ici c'est un FAUX positif : le serveur Django
# (`live_server`) tourne dans SON propre thread, pas dans la boucle Playwright.
# On lève donc la garde — uniquement pour le paquet e2e (ce conftest est local à
# src/tests/e2e/, il n'est pas chargé par le reste de la suite).
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

# Identifiants de l'utilisateur de démo E2E. Mot de passe GÉNÉRÉ au runtime (aucun
# littéral à scanner — GitGuardian) : la connexion passe par le vrai formulaire avec
# CETTE même variable au create_user ET au login, et le login Django ne valide pas la
# robustesse du mot de passe (seul le signup le fait) → un secret aléatoire convient.
E2E_EMAIL = "e2e.user@bricbudget.test"
E2E_PASSWORD = secrets.token_urlsafe(16)


def pytest_collection_modifyitems(config, items):
    """
    Marque tout test de tests/e2e/ avec `e2e` automatiquement.

    Pourquoi : la suite par défaut s'exécute avec `-m "not e2e"` (addopts) pour
    NE PAS lancer les tests navigateur quand chromium est absent (pre-push, job
    CI principal). En taguant ici, on garantit qu'aucun test E2E n'échappe au
    filtre par oubli de décorateur.
    """
    for item in items:
        # rootpath-relative : ne tagger que ce qui vit réellement sous tests/e2e/.
        if "tests/e2e/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


@pytest.fixture
def e2e_user(transactional_db):
    """
    Crée l'utilisateur de démo E2E via l'ORM.

    `transactional_db` (et non `db`) car `live_server` tourne dans un autre thread :
    la donnée doit être committée pour être visible côté serveur. pytest-django
    rend `live_server` dépendant de `transactional_db` — on s'aligne ici pour que
    l'ordre de setup soit correct quand un test demande `e2e_user` et `live_server`.
    """
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        email=E2E_EMAIL,
        password=E2E_PASSWORD,
        first_name="Emma",
        last_name="Test",
    )
    return user


def login(page, live_server, email=E2E_EMAIL, password=E2E_PASSWORD):
    """
    Connexion via le VRAI formulaire de login (pas de force_login).

    Le formulaire Django `AuthenticationForm` rend le champ identifiant sous
    `name="username"` même si USERNAME_FIELD = email (le label affiché est
    « Email ») → on remplit `username` avec l'email. Après submit, Django
    redirige vers LOGIN_REDIRECT_URL = /budget/.

    On attend la navigation post-submit pour éviter les races (le clic déclenche
    un POST + redirect 302 → GET /budget/).
    """
    page.goto(f"{live_server.url}/login/")
    page.fill("input[name='username']", email)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")
    # wait_for_url couvre le POST → 302 → GET /budget/ : on ne continue que
    # lorsque l'URL finale est atteinte (le dashboard est rendu). Pattern idiomatique
    # Playwright 1.x (cohérent avec test_navigation.py), sans la race d'expect_navigation
    # (déprécié) où la navigation peut démarrer avant l'entrée du context manager.
    page.wait_for_url(f"{live_server.url}/budget/")
    return page
