"""
tests/services/test_logos.py — micro-service logos (services/logos.py).

Tests PURS : aucun accès DB, aucun accès réseau. Le primitif réseau
services.logos._download est mocké (monkeypatch). Le système de fichiers
passe par tmp_path.

Contrat du service :
    is_valid_domain  — regex anti-injection URL (porté d'update_bank_logos)
    fetch_logo       — domaine → PNG à dest ; None si échec, ne lève JAMAIS
    has_logo         — logo présent = svg/<slug>.svg OU miniature/<slug>.{png,jpg,jpeg}
                       (même logique de résolution que le tag institution_icon_url)
"""

from pathlib import Path

import pytest

from services import logos

# ── is_valid_domain ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "domain", ["yuh.ch", "home.saxo", "credit-agricole.fr", "n26.com"]
)
def test_is_valid_domain_accepts_real_domains(domain):
    assert logos.is_valid_domain(domain) is True


@pytest.mark.parametrize(
    "domain",
    [
        "",  # vide
        "https://yuh.ch",  # scheme → injection URL
        "yuh.ch/path",  # slash → path injection
        "yuh.ch?x=1",  # query string
        "UBS.COM",  # majuscules (convention : domaines stockés en minuscules)
        "yuh .ch",  # espace
    ],
)
def test_is_valid_domain_rejects_garbage(domain):
    assert logos.is_valid_domain(domain) is False


# ── fetch_logo ────────────────────────────────────────────────────────────────


def test_fetch_logo_success_writes_dest_and_returns_path(tmp_path, monkeypatch):
    """Cas nominal : _download écrit le fichier → fetch_logo retourne dest."""
    seen_urls: list[str] = []

    def fake_download(url: str, dest: Path) -> None:
        seen_urls.append(url)
        dest.write_bytes(b"\x89PNG fake")

    monkeypatch.setattr(logos, "_download", fake_download)
    dest = tmp_path / "yuh.png"

    result = logos.fetch_logo("yuh.ch", dest)

    assert result == dest
    assert dest.is_file()
    # L'URL contient le domaine et la taille par défaut (128).
    assert "yuh.ch" in seen_urls[0]
    assert "128" in seen_urls[0]


def test_fetch_logo_passes_custom_size(tmp_path, monkeypatch):
    seen_urls: list[str] = []

    def fake_download(url: str, dest: Path) -> None:
        seen_urls.append(url)
        dest.write_bytes(b"x")

    monkeypatch.setattr(logos, "_download", fake_download)

    logos.fetch_logo("yuh.ch", tmp_path / "yuh.png", size=64)

    assert "64" in seen_urls[0]


def test_fetch_logo_invalid_domain_returns_none_without_download(tmp_path, monkeypatch):
    """Domaine invalide → refus AVANT tout accès réseau (anti-injection)."""

    def fake_download(url: str, dest: Path) -> None:  # pragma: no cover
        raise AssertionError("_download ne doit pas être appelé")

    monkeypatch.setattr(logos, "_download", fake_download)

    assert logos.fetch_logo("https://evil.com/x", tmp_path / "x.png") is None


def test_fetch_logo_download_error_returns_none(tmp_path, monkeypatch):
    """Erreur réseau → None (loggé), jamais d'exception qui remonte à l'appelant."""

    def fake_download(url: str, dest: Path) -> None:
        raise OSError("network down")

    monkeypatch.setattr(logos, "_download", fake_download)

    assert logos.fetch_logo("yuh.ch", tmp_path / "yuh.png") is None


def test_fetch_logo_empty_file_returns_none_and_cleans_up(tmp_path, monkeypatch):
    """Fichier vide (réponse cassée) → échec + pas de fichier fantôme laissé derrière."""

    def fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(b"")

    monkeypatch.setattr(logos, "_download", fake_download)
    dest = tmp_path / "yuh.png"

    assert logos.fetch_logo("yuh.ch", dest) is None
    assert not dest.exists()


def test_fetch_logo_creates_parent_dirs(tmp_path, monkeypatch):
    """Le dossier de destination est créé si absent (premier run sur machine vierge)."""

    def fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(b"x")

    monkeypatch.setattr(logos, "_download", fake_download)
    dest = tmp_path / "icons" / "institutions" / "miniature" / "yuh.png"

    assert logos.fetch_logo("yuh.ch", dest) == dest


def test_fetch_logo_falls_back_to_www_when_bare_domain_fails(tmp_path, monkeypatch):
    """L'index favicon Google ne connaît parfois QUE www.<domaine> (cas réel :
    zkb.ch → 404, www.zkb.ch → 200). Le service retente en www. avant d'abandonner."""
    seen_urls: list[str] = []

    def fake_download(url: str, dest: Path) -> None:
        seen_urls.append(url)
        if "domain=www." not in url:
            raise OSError("404 — domaine nu inconnu de l'index")
        dest.write_bytes(b"x")

    monkeypatch.setattr(logos, "_download", fake_download)
    dest = tmp_path / "zkb.png"

    assert logos.fetch_logo("zkb.ch", dest) == dest
    assert len(seen_urls) == 2
    assert "domain=zkb.ch" in seen_urls[0]
    assert "domain=www.zkb.ch" in seen_urls[1]


def test_fetch_logo_no_double_www(tmp_path, monkeypatch):
    """Domaine déjà en www. → un seul essai (pas de www.www.)."""
    seen_urls: list[str] = []

    def fake_download(url: str, dest: Path) -> None:
        seen_urls.append(url)
        raise OSError("404")

    monkeypatch.setattr(logos, "_download", fake_download)

    assert logos.fetch_logo("www.zkb.ch", tmp_path / "x.png") is None
    assert len(seen_urls) == 1


# ── has_logo ──────────────────────────────────────────────────────────────────


def _base(tmp_path: Path) -> Path:
    """Arborescence static/icons/institutions vide : svg/ + miniature/."""
    (tmp_path / "svg").mkdir()
    (tmp_path / "miniature").mkdir()
    return tmp_path


def test_has_logo_false_when_nothing(tmp_path):
    assert logos.has_logo("yuh", _base(tmp_path)) is False


def test_has_logo_true_with_svg(tmp_path):
    base = _base(tmp_path)
    (base / "svg" / "yuh.svg").write_text("<svg/>")
    assert logos.has_logo("yuh", base) is True


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg"])
def test_has_logo_true_with_miniature(tmp_path, ext):
    base = _base(tmp_path)
    (base / "miniature" / f"yuh.{ext}").write_bytes(b"x")
    assert logos.has_logo("yuh", base) is True


def test_has_logo_ignores_other_slugs(tmp_path):
    base = _base(tmp_path)
    (base / "miniature" / "ubs.png").write_bytes(b"x")
    assert logos.has_logo("yuh", base) is False
