"""
tests/accounts/test_logo_signal.py — post_save Institution → auto-fetch du logo.

« Au fil de l'eau » : sauver une Institution avec un domain et sans logo déclenche
fetch_logo en best-effort. Jamais bloquant : un échec de fetch ne fait pas échouer
le save. Réseau jamais touché (fetch_logo monkeypatché ; et le garde global de
tests/conftest.py neutralise _download de toute façon).
"""

from pathlib import Path

import pytest

from accounts.models import Institution
from services import logos


@pytest.fixture
def icon_base(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "svg").mkdir()
    (tmp_path / "miniature").mkdir()
    monkeypatch.setattr(logos, "institutions_icon_base", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def fetch_calls(monkeypatch) -> list[tuple[str, Path]]:
    calls: list[tuple[str, Path]] = []

    def fake_fetch(domain: str, dest: Path, *, size: int = 128) -> Path:
        calls.append((domain, dest))
        return dest

    monkeypatch.setattr(logos, "fetch_logo", fake_fetch)
    return calls


@pytest.mark.django_db
def test_save_with_domain_and_no_logo_fetches(icon_base, fetch_calls):
    Institution.objects.create(
        name="Neon",
        slug="neon",
        country="CH",
        default_currency="CHF",
        icon_slug="neon",
        domain="neon-free.ch",
    )

    assert fetch_calls == [("neon-free.ch", icon_base / "miniature" / "neon.png")]


@pytest.mark.django_db
def test_save_without_domain_does_nothing(icon_base, fetch_calls):
    """Cas de toutes les fixtures de la suite : domain vide → aucun fetch."""
    Institution.objects.create(
        name="Test CHF",
        slug="pat-chf",
        country="CH",
        default_currency="CHF",
    )

    assert fetch_calls == []


@pytest.mark.django_db
def test_save_with_existing_logo_does_nothing(icon_base, fetch_calls):
    (icon_base / "miniature" / "yuh.png").write_bytes(b"x")

    Institution.objects.create(
        name="Yuh",
        slug="yuh",
        country="CH",
        default_currency="CHF",
        icon_slug="yuh",
        domain="yuh.ch",
    )

    assert fetch_calls == []


@pytest.mark.django_db
def test_save_succeeds_even_if_fetch_fails(icon_base, monkeypatch):
    """Best-effort : fetch_logo → None (échec réseau) — le save aboutit quand même."""
    monkeypatch.setattr(logos, "fetch_logo", lambda *a, **k: None)

    inst = Institution.objects.create(
        name="Yuh",
        slug="yuh",
        country="CH",
        default_currency="CHF",
        icon_slug="yuh",
        domain="yuh.ch",
    )

    assert inst.pk is not None


@pytest.mark.django_db
def test_icon_slug_fallback_to_slug(icon_base, fetch_calls):
    Institution.objects.create(
        name="Neon",
        slug="neon",
        country="CH",
        default_currency="CHF",
        icon_slug="",
        domain="neon-free.ch",
    )

    assert fetch_calls == [("neon-free.ch", icon_base / "miniature" / "neon.png")]
