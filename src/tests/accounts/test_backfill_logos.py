"""
tests/accounts/test_backfill_logos.py — commande backfill_logos (one-shot dev).

La commande parcourt les Institutions et récupère les logos MANQUANTS via le
micro-service services/logos.py. Réseau jamais touché ici : fetch_logo est
monkeypatché ; le répertoire static réel est remplacé par tmp_path via
banks_icon_base (sinon les slugs du repo — yuh, ubs… — fausseraient has_logo).
"""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db.models.signals import post_save

from accounts.models import Institution
from services import logos


@pytest.fixture(autouse=True)
def _mute_logo_signal():
    """
    Coupe le post_save Institution (auto-fetch logo) pendant ces tests : il se
    déclencherait à la création des fixtures et fausserait fetch_calls — ici on
    teste la COMMANDE seule, le signal a ses propres tests (test_logo_signal.py).
    """
    disconnected = post_save.disconnect(
        sender=Institution, dispatch_uid="institution_logo_autofetch"
    )
    yield
    if disconnected:
        from accounts.signals import fetch_institution_logo

        post_save.connect(
            fetch_institution_logo,
            sender=Institution,
            dispatch_uid="institution_logo_autofetch",
        )


@pytest.fixture
def icon_base(tmp_path: Path, monkeypatch) -> Path:
    """static/icons/banks isolé (svg/ + miniature/) + banks_icon_base patché."""
    (tmp_path / "svg").mkdir()
    (tmp_path / "miniature").mkdir()
    monkeypatch.setattr(logos, "banks_icon_base", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def fetch_calls(monkeypatch) -> list[tuple[str, Path]]:
    """Capture les appels fetch_logo (succès simulé : écrit le fichier)."""
    calls: list[tuple[str, Path]] = []

    def fake_fetch(domain: str, dest: Path, *, size: int = 128) -> Path:
        calls.append((domain, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return dest

    monkeypatch.setattr(logos, "fetch_logo", fake_fetch)
    return calls


def _make_institution(slug: str, *, domain: str = "", icon_slug: str | None = None):
    return Institution.objects.create(
        name=slug.upper(),
        slug=slug,
        country="CH",
        default_currency="CHF",
        icon_slug=slug if icon_slug is None else icon_slug,
        domain=domain,
    )


def _run(*args) -> str:
    out = StringIO()
    call_command("backfill_logos", *args, stdout=out, stderr=out)
    return out.getvalue()


@pytest.mark.django_db
def test_fetches_missing_logo(icon_base, fetch_calls):
    _make_institution("yuh", domain="yuh.ch")

    _run()

    assert fetch_calls == [("yuh.ch", icon_base / "miniature" / "yuh.png")]


@pytest.mark.django_db
def test_skips_when_logo_already_present(icon_base, fetch_calls):
    """Idempotent : un logo déjà sur disque (png OU svg) n'est pas re-téléchargé."""
    _make_institution("yuh", domain="yuh.ch")
    _make_institution("ubs", domain="ubs.com")
    (icon_base / "miniature" / "yuh.png").write_bytes(b"x")
    (icon_base / "svg" / "ubs.svg").write_text("<svg/>")

    _run()

    assert fetch_calls == []


@pytest.mark.django_db
def test_force_refetches_existing(icon_base, fetch_calls):
    _make_institution("yuh", domain="yuh.ch")
    (icon_base / "miniature" / "yuh.png").write_bytes(b"x")

    _run("--force")

    assert [c[0] for c in fetch_calls] == ["yuh.ch"]


@pytest.mark.django_db
def test_skips_without_domain(icon_base, fetch_calls):
    _make_institution("mystery", domain="")

    out = _run()

    assert fetch_calls == []
    assert "domain vide" in out


@pytest.mark.django_db
def test_filters_by_institution_slug(icon_base, fetch_calls):
    _make_institution("yuh", domain="yuh.ch")
    _make_institution("ubs", domain="ubs.com")

    _run("--institution", "yuh")

    assert [c[0] for c in fetch_calls] == ["yuh.ch"]


@pytest.mark.django_db
def test_falls_back_to_slug_when_icon_slug_empty(icon_base, fetch_calls):
    """icon_slug vide → le slug sert de nom de fichier (même règle que bank_icon_url)."""
    _make_institution("neon", domain="neon-free.ch", icon_slug="")

    _run()

    assert fetch_calls == [("neon-free.ch", icon_base / "miniature" / "neon.png")]


@pytest.mark.django_db
def test_reports_failed_fetch_without_stopping(icon_base, monkeypatch):
    """Un fetch raté (None) n'interrompt pas le backfill des suivants."""
    _make_institution("aaa-broken", domain="broken.invalid")
    _make_institution("zzz-ok", domain="ok.ch")
    results: list[str] = []

    def flaky_fetch(domain: str, dest: Path, *, size: int = 128):
        results.append(domain)
        if domain == "broken.invalid":
            return None
        dest.write_bytes(b"x")
        return dest

    monkeypatch.setattr(logos, "fetch_logo", flaky_fetch)

    out = _run()

    # Les deux ont été tentés malgré l'échec du premier (ordre par slug).
    assert results == ["broken.invalid", "ok.ch"]
    assert "échec" in out
