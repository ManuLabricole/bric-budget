"""
tests/accounts/test_seed_banks.py — seed du catalogue d'institutions.

Vérifie que seed_banks matérialise KNOWN_INSTITUTIONS en DB : création complète,
domain/icon_slug posés, idempotence (re-run = mise à jour, pas de doublon),
--dry-run sans écriture. Le fetch de logo (post_save) est neutralisé : ici on
teste le SEED, le signal a ses propres tests (test_logo_signal.py).
"""

from io import StringIO

import pytest
from django.core.management import call_command

from accounts.institutions_config import KNOWN_INSTITUTIONS
from accounts.models import Institution
from services import logos


@pytest.fixture(autouse=True)
def _no_logo_fetch(monkeypatch):
    """Le post_save Institution tenterait un fetch par entrée — inutile ici."""
    monkeypatch.setattr(logos, "fetch_logo", lambda *a, **k: None)


def _run(*args) -> str:
    out = StringIO()
    call_command("seed_banks", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_seed_creates_every_known_institution():
    _run()

    assert Institution.objects.count() == len(KNOWN_INSTITUTIONS)


@pytest.mark.django_db
def test_seed_sets_domain_icon_slug_and_fields():
    _run()

    yuh = Institution.objects.get(slug="yuh")
    assert yuh.domain == "yuh.ch"
    assert yuh.icon_slug == "yuh"
    assert yuh.country == "CH"
    assert yuh.default_currency == "CHF"
    # Toutes les entrées du catalogue portent un domain (logo récupérable).
    assert not Institution.objects.filter(domain="").exists()


@pytest.mark.django_db
def test_seed_sets_category():
    """Le badge UI : seed_banks pose la category depuis la config (3 valeurs)."""
    _run()

    assert Institution.objects.get(slug="yuh").category == "bank"
    assert Institution.objects.get(slug="binance").category == "crypto"
    # Assurance vie / prévoyance rangées en "investment" (décision 3 catégories).
    assert Institution.objects.get(slug="spirica").category == "investment"
    assert Institution.objects.get(slug="finpension").category == "investment"
    # Aucune catégorie hors du set autorisé.
    valid = {"bank", "investment", "crypto"}
    assert set(Institution.objects.values_list("category", flat=True)) <= valid


@pytest.mark.django_db
def test_seed_is_idempotent():
    """2 runs → même nombre de lignes, les champs sont resynchronisés depuis la config."""
    _run()
    # Dérive simulée (modif manuelle en DB) → le re-seed doit resynchroniser.
    Institution.objects.filter(slug="yuh").update(domain="hacked.example")

    _run()

    assert Institution.objects.count() == len(KNOWN_INSTITUTIONS)
    assert Institution.objects.get(slug="yuh").domain == "yuh.ch"


@pytest.mark.django_db
def test_dry_run_writes_nothing():
    out = _run("--dry-run")

    assert Institution.objects.count() == 0
    assert "dry-run" in out
