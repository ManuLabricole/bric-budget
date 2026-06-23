"""
tests/demo/test_admin_seed.py — page admin « Données de démo » (#118).

Vérifie le câblage de la vue (pas seed_demo lui-même, testé ailleurs) :
staff requis, rendu des boutons, dispatch seed/reset, et le dev-guard
(refus d'agir quand DEBUG=False) — comme les commandes dev_seed/dev_reset.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(
        email="staff@bric.test", password="x", is_staff=True, is_superuser=True
    )


@pytest.fixture
def plain(db):
    return get_user_model().objects.create_user(email="plain@bric.test", password="x")


@pytest.mark.django_db
def test_requires_staff(client, plain):
    """Un user non-staff est redirigé (admin_view → login)."""
    client.force_login(plain)
    r = client.get(reverse("demo_seed_control"))
    assert r.status_code == 302


@pytest.mark.django_db
def test_get_renders_buttons_for_staff(client, staff):
    client.force_login(staff)
    r = client.get(reverse("demo_seed_control"))
    assert r.status_code == 200
    body = r.content.decode()
    assert 'value="seed"' in body
    assert 'value="reset"' in body


@pytest.mark.django_db
def test_post_seed_refused_when_not_debug(client, staff, settings):
    """DEBUG=False → la vue NE déclenche PAS le seed (dev-guard), redirige quand même."""
    settings.DEBUG = False
    client.force_login(staff)
    with patch("demo.seeder.seed_demo") as mock_seed:
        r = client.post(reverse("demo_seed_control"), {"action": "seed"})
    assert r.status_code == 302
    mock_seed.assert_not_called()


@pytest.mark.django_db
def test_post_seed_runs_when_debug(client, staff, settings):
    settings.DEBUG = True
    client.force_login(staff)
    summary = SimpleNamespace(
        accounts=6, imports=6, created=311, rules=22, skipped=0, user_email="demo@x"
    )
    with patch("demo.seeder.seed_demo", return_value=summary) as mock_seed:
        r = client.post(reverse("demo_seed_control"), {"action": "seed"})
    assert r.status_code == 302
    mock_seed.assert_called_once_with(flush=True)


@pytest.mark.django_db
def test_post_reset_runs_when_debug(client, staff, settings):
    settings.DEBUG = True
    client.force_login(staff)
    with patch("demo.seeder.reset_demo", return_value="demo@x") as mock_reset:
        r = client.post(reverse("demo_seed_control"), {"action": "reset"})
    assert r.status_code == 302
    mock_reset.assert_called_once()


@pytest.mark.django_db
def test_post_unknown_action_is_noop(client, staff, settings):
    settings.DEBUG = True
    client.force_login(staff)
    with patch("demo.seeder.seed_demo") as mock_seed:
        r = client.post(reverse("demo_seed_control"), {"action": "bogus"})
    assert r.status_code == 302
    mock_seed.assert_not_called()
