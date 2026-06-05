"""tests/patrimoine/test_filters.py — filtre par classe d'actifs (session, PRG)."""

import pytest
from django.urls import reverse

from patrimoine.views.filters import FILTER_SESSION_KEY


@pytest.mark.django_db
def test_toggle_unchecks_a_class(client, user):
    client.force_login(user)
    resp = client.post(reverse("patrimoine:toggle_class", args=["crypto"]))
    assert resp.status_code == 302  # PRG
    assert "crypto" not in client.session[FILTER_SESSION_KEY]
    assert "comptes-courants" in client.session[FILTER_SESSION_KEY]


@pytest.mark.django_db
def test_toggle_all_reselects_everything(client, user):
    client.force_login(user)
    client.post(reverse("patrimoine:toggle_class", args=["crypto"]))
    client.post(reverse("patrimoine:toggle_class", args=["all"]))
    assert "crypto" in client.session[FILTER_SESSION_KEY]


@pytest.mark.django_db
def test_toggle_unknown_class_404(client, user):
    client.force_login(user)
    resp = client.post(reverse("patrimoine:toggle_class", args=["bidon"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_toggle_requires_post(client, user):
    client.force_login(user)
    resp = client.get(reverse("patrimoine:toggle_class", args=["crypto"]))
    assert resp.status_code == 405


@pytest.mark.django_db
def test_overview_hides_unselected_class(client, user, chf_account):
    """Une classe décochée disparaît des nœuds de la table (le filtre la liste encore)."""
    client.force_login(user)
    client.post(reverse("patrimoine:toggle_class", args=["crypto"]))
    resp = client.get(reverse("patrimoine:overview"))
    labels = {n.label for n in resp.context["nodes"]}
    assert "Comptes courants" in labels
    assert "Crypto" not in labels
