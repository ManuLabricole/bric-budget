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
from django.test import override_settings

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


# ── get_institution_icon_map / institution_icon_url (#139) ──────────────────────
#
# get_institution_icon_map est un lru_cache GLOBAL au process → on vide le cache
# avant ET après chaque test : avant pour ignorer ce qu'un test précédent a mis,
# après pour ne pas polluer les tests de vues qui résolvent depuis le vrai disque.


@pytest.fixture
def clear_icon_cache():
    logos.clear_institution_icon_cache()
    yield
    logos.clear_institution_icon_cache()


def test_get_institution_icon_map_returns_dict(clear_icon_cache, monkeypatch):
    monkeypatch.setattr(
        logos, "_build_institution_icon_map", lambda: {"yuh": "/static/yuh.svg"}
    )
    result = logos.get_institution_icon_map()
    assert isinstance(result, dict)
    assert result["yuh"] == "/static/yuh.svg"


def test_get_institution_icon_map_cached(clear_icon_cache, monkeypatch):
    """lru_cache → 2 appels = même objet (référence identique)."""
    monkeypatch.setattr(logos, "_build_institution_icon_map", lambda: {})
    assert logos.get_institution_icon_map() is logos.get_institution_icon_map()


def test_icon_url_builds_map_once_for_n_resolutions(clear_icon_cache, monkeypatch):
    """Contrat #139 : N résolutions unitaires → 1 seul scan disque (anti-N+1)."""
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return {"yuh": "/static/yuh.svg"}

    monkeypatch.setattr(logos, "_build_institution_icon_map", counting)
    for _ in range(50):
        logos.institution_icon_url("yuh")
    assert calls["n"] == 1


def test_institution_icon_url_resolves_slug_or_empty(clear_icon_cache, monkeypatch):
    monkeypatch.setattr(
        logos, "_build_institution_icon_map", lambda: {"yuh": "/static/yuh.svg"}
    )
    assert logos.institution_icon_url("yuh") == "/static/yuh.svg"
    assert logos.institution_icon_url("unknown") == ""


def test_institution_icon_url_coerces_object(clear_icon_cache, monkeypatch):
    """Objet Institution : icon_slug prioritaire sur slug."""
    monkeypatch.setattr(
        logos, "_build_institution_icon_map", lambda: {"yuh": "/static/yuh.svg"}
    )

    class Inst:
        icon_slug = "yuh"
        slug = "ignored"

    assert logos.institution_icon_url(Inst()) == "/static/yuh.svg"


def test_institution_icon_url_object_without_icon_slug_returns_empty(
    clear_icon_cache, monkeypatch
):
    """icon_slug=None ET slug="" → "" (le composant affiche alors l'initiale)."""
    monkeypatch.setattr(logos, "_build_institution_icon_map", lambda: {"yuh": "/x.svg"})

    class Inst:
        icon_slug = None
        slug = ""

    assert logos.institution_icon_url(Inst()) == ""


def test_build_institution_icon_map_svg_overrides_miniature(tmp_path, monkeypatch):
    """SVG prioritaire sur miniature pour un même slug (scan disque réel).

    Pas de clear_icon_cache : on appelle _build_institution_icon_map() directement,
    sans passer par le map caché → aucun risque de pollution inter-tests.
    """
    base = _base(tmp_path)
    (base / "miniature" / "yuh.png").write_bytes(b"x")
    (base / "svg" / "yuh.svg").write_text("<svg/>")
    monkeypatch.setattr(logos, "institutions_icon_base", lambda: base)
    result = logos._build_institution_icon_map()
    assert result["yuh"].endswith("/svg/yuh.svg")


# ── fetch_from_url — réparation manuelle par URL (#128) ─────────────────────────
#
# Storage MEDIA en mémoire (InMemoryStorage) → aucun fichier sur disque, aucun réseau
# (_download_url monkeypatché). override_settings réinitialise le handler de storage
# entre les tests → isolation.

_INMEM_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_installs_png_and_invalidates_cache(
    clear_icon_cache, monkeypatch
):
    monkeypatch.setattr(
        logos, "_download_url", lambda url: (b"\x89PNG-fake", "image/png")
    )
    name = logos.fetch_from_url("https://bank.example/logo.png", "zkb")
    assert name == "icons/institutions/zkb.png"
    # cache_clear interne → le slug apparaît immédiatement dans le map résolu.
    assert "zkb" in logos.get_institution_icon_map()


@override_settings(STORAGES=_INMEM_STORAGES)
@pytest.mark.parametrize(
    "url",
    [
        "http://bank.example/logo.png",  # pas https
        "https://127.0.0.1/logo.png",  # IP littérale (réseau privé)
        "https://localhost/logo.png",  # localhost
        "https://169.254.169.254/meta.png",  # métadonnées cloud (SSRF classique)
        "https://service.internal/logo.png",  # suffixe interne
    ],
)
def test_fetch_from_url_refuses_unsafe_url_without_network(url, monkeypatch):
    touched = {"net": False}

    def spy(_u):
        touched["net"] = True
        return (b"x", "image/png")

    monkeypatch.setattr(logos, "_download_url", spy)
    assert logos.fetch_from_url(url, "zkb") is None
    assert touched["net"] is False  # garde SSRF : le réseau n'est jamais touché


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_rejects_unknown_content_type(monkeypatch):
    # Content-type ni raster ni SVG → refusé (extension dérivée du content-type).
    monkeypatch.setattr(logos, "_download_url", lambda url: (b"<html>", "text/html"))
    assert logos.fetch_from_url("https://bank.example/logo.png", "zkb") is None


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_accepts_safe_svg(clear_icon_cache, monkeypatch):
    monkeypatch.setattr(
        logos,
        "_download_url",
        lambda url: (b'<svg xmlns="..."><path d="M0 0"/></svg>', "image/svg+xml"),
    )
    name = logos.fetch_from_url("https://descartes.swiss/logo.svg", "descartes")
    assert name == "icons/institutions/descartes.svg"


@override_settings(STORAGES=_INMEM_STORAGES)
@pytest.mark.parametrize(
    "payload",
    [
        b'<svg onload="alert(1)"></svg>',  # handler inline (espace)
        b'<svg/onload="alert(1)"></svg>',  # handler inline SANS espace (F3)
        b"<svg><script>alert(1)</script></svg>",  # script embarqué
        b'<svg><a href="javascript:alert(1)">x</a></svg>',  # uri javascript
        b"<svg><foreignObject></foreignObject></svg>",  # html arbitraire
    ],
)
def test_fetch_from_url_rejects_unsafe_svg(payload, monkeypatch):
    # ⛔ SVG avec script/handler refusé (garde anti-XSS), même content-type valide.
    monkeypatch.setattr(logos, "_download_url", lambda url: (payload, "image/svg+xml"))
    assert logos.fetch_from_url("https://bank.example/logo.svg", "zkb") is None


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_svg_content_type_spoof_still_guarded(monkeypatch):
    """F2 anti-spoof : corps SVG malveillant annoncé image/png → quand même refusé."""
    monkeypatch.setattr(
        logos,
        "_download_url",
        lambda url: (b'<svg onload="alert(1)"></svg>', "image/png"),
    )
    assert logos.fetch_from_url("https://bank.example/logo.png", "zkb") is None


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_svg_body_forces_svg_extension(clear_icon_cache, monkeypatch):
    """Corps SVG (sain) annoncé image/png → stocké en .svg (extension dérivée du contenu)."""
    monkeypatch.setattr(
        logos, "_download_url", lambda url: (b"<svg><path/></svg>", "image/png")
    )
    name = logos.fetch_from_url("https://bank.example/logo.png", "zkb")
    assert name == "icons/institutions/zkb.svg"


def test_no_redirect_handler_raises_on_30x():
    """F1 anti-SSRF : suivre une redirection est refusé (lève HTTPError → fetch logge failed)."""
    import io
    import urllib.error

    handler = logos._NoRedirectHandler()
    req = urllib.request.Request("https://evil.example/logo.png")
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            req, io.BytesIO(b""), 302, "Found", {}, "http://169.254.169.254/"
        )


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_rejects_too_large(monkeypatch):
    oversized = b"x" * (512 * 1024 + 1)
    monkeypatch.setattr(logos, "_download_url", lambda url: (oversized, "image/png"))
    assert logos.fetch_from_url("https://bank.example/logo.png", "zkb") is None


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_rejects_empty_response(monkeypatch):
    monkeypatch.setattr(logos, "_download_url", lambda url: (b"", "image/png"))
    assert logos.fetch_from_url("https://bank.example/logo.png", "zkb") is None


@override_settings(STORAGES=_INMEM_STORAGES)
def test_fetch_from_url_download_error_returns_none(monkeypatch):
    def boom(_u):
        raise OSError("network down")

    monkeypatch.setattr(logos, "_download_url", boom)
    assert logos.fetch_from_url("https://bank.example/logo.png", "zkb") is None


@override_settings(STORAGES=_INMEM_STORAGES)
def test_repaired_logo_priority_miniature_then_storage_then_svg(
    clear_icon_cache, tmp_path, monkeypatch
):
    """Priorité de résolution : miniature (static) < logo réparé (storage) < svg."""
    base = _base(tmp_path)
    (base / "miniature" / "zkb.png").write_bytes(b"x")
    monkeypatch.setattr(logos, "institutions_icon_base", lambda: base)
    monkeypatch.setattr(logos, "_download_url", lambda url: (b"fake", "image/png"))

    # 1. miniature seule → c'est elle qui résout.
    assert "miniature" in logos.get_institution_icon_map()["zkb"]

    # 2. logo réparé installé → bat la miniature.
    logos.fetch_from_url("https://bank.example/logo.png", "zkb")
    assert "miniature" not in logos.get_institution_icon_map()["zkb"]

    # 3. SVG curé ajouté → bat le logo réparé.
    (base / "svg" / "zkb.svg").write_text("<svg/>")
    logos.clear_institution_icon_cache()
    assert logos.get_institution_icon_map()["zkb"].endswith("/svg/zkb.svg")
