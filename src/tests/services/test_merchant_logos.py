"""
tests/services/test_merchant_logos.py — services/merchant_logos.py.

Tests PURS : aucun réseau. services.logos.fetch_from_url est mocké (boundary —
sa propre correction anti-SSRF/anti-XSS est prouvée par test_logos.py, on ne la
reteste pas ici). Le seed est un petit JSON écrit dans tmp_path, pas le vrai
fichier de référence (isolation — un ajout au vrai seed ne doit jamais casser
ce test).
"""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from services import merchant_logos


@pytest.fixture
def small_seed(tmp_path, monkeypatch):
    """Seed minimal et déterministe — ordre : uber avant paypal (priorité)."""
    path = tmp_path / "merchant_seed.json"
    path.write_text(
        json.dumps(
            {
                "merchants": [
                    {
                        "key": "uber",
                        "name": "Uber",
                        "domain": "uber.com",
                        "keywords": ["UBER"],
                    },
                    {
                        "key": "paypal",
                        "name": "PayPal",
                        "domain": "paypal.com",
                        "keywords": ["PAYPAL"],
                    },
                    {
                        "key": "youtube",
                        "name": "YouTube",
                        "domain": "youtube.com",
                        "keywords": ["YOUTUBE"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    merchant_logos.load_seed.cache_clear()
    monkeypatch.setattr(merchant_logos, "SEED_PATH", path)
    yield path
    merchant_logos.load_seed.cache_clear()


@pytest.fixture
def clear_manual_cache():
    merchant_logos.clear_manual_logo_cache()
    yield
    merchant_logos.clear_manual_logo_cache()


# ── resolve_seed_key ──────────────────────────────────────────────────────────


def test_resolve_seed_key_matches_known_keyword(small_seed):
    assert merchant_logos.resolve_seed_key("HELP.UBER.COM UBER *EATS") == "uber"


def test_resolve_seed_key_returns_none_when_no_keyword_matches(small_seed):
    assert merchant_logos.resolve_seed_key("GRENOBLE TABAC LE SAINT C") is None


def test_resolve_seed_key_prefers_specific_entry_over_generic_by_order(small_seed):
    """uber est placé AVANT paypal dans le seed → gagne sur "PAYPAL *UBER BV"."""
    assert merchant_logos.resolve_seed_key("PAYPAL *UBER BV") == "uber"


def test_resolve_seed_key_matches_truncated_suffix_left_boundary_only(small_seed):
    """ "GOOGLE YOUTUBEPR" — troncature bancaire, sans espace après le mot-clé."""
    assert merchant_logos.resolve_seed_key("12,99 EUR GOOGLE YOUTUBEPR") == "youtube"


def test_resolve_seed_key_does_not_match_word_embedded_mid_string(small_seed):
    """Frontière à gauche : "UBER" ne doit pas matcher dans un mot qui le contient."""
    assert merchant_logos.resolve_seed_key("SNUBERTS BAKERY") is None


# ── slug_for ──────────────────────────────────────────────────────────────────


def test_slug_for_is_stable_across_calls():
    a = merchant_logos.slug_for("Grenoble Tabac Le Saint C")
    b = merchant_logos.slug_for("Grenoble Tabac Le Saint C")
    assert a == b


def test_slug_for_truncates_long_names():
    long_name = "A" * 200
    assert len(merchant_logos.slug_for(long_name)) == merchant_logos._SLUG_MAX_LENGTH


# ── get_merchant_logo_map ─────────────────────────────────────────────────────


def test_get_merchant_logo_map_manual_override_wins_over_seed(
    small_seed, clear_manual_cache, monkeypatch
):
    """Un logo ajouté à la main pour CE display_name gagne sur le match seed."""
    monkeypatch.setattr(
        merchant_logos.logos,
        "listdir_urls",
        lambda prefix: {
            merchant_logos.slug_for("MA BOUTIQUE UBER"): "/media/manual.png"
        },
    )
    result = merchant_logos.get_merchant_logo_map(["MA BOUTIQUE UBER"])
    assert result["MA BOUTIQUE UBER"] == "/media/manual.png"


@override_settings(BRANDFETCH_CLIENT_ID="test-client-id")
def test_get_merchant_logo_map_falls_back_to_seed_brandfetch_url_when_no_manual_entry(
    small_seed, clear_manual_cache, monkeypatch
):
    monkeypatch.setattr(merchant_logos.logos, "listdir_urls", lambda prefix: {})
    result = merchant_logos.get_merchant_logo_map(["HELP.UBER.COM UBER *EATS"])
    assert result["HELP.UBER.COM UBER *EATS"] == (
        "https://cdn.brandfetch.io/domain/uber.com/theme/light/w/48/h/48"
        "/fallback/404/icon.png?c=test-client-id"
    )


@override_settings(BRANDFETCH_CLIENT_ID="")
def test_get_merchant_logo_map_seed_match_without_client_id_returns_empty(
    small_seed, clear_manual_cache, monkeypatch
):
    """Pas de Client ID configuré (dev sans .env rempli) → dégradation silencieuse."""
    monkeypatch.setattr(merchant_logos.logos, "listdir_urls", lambda prefix: {})
    result = merchant_logos.get_merchant_logo_map(["HELP.UBER.COM UBER *EATS"])
    assert result["HELP.UBER.COM UBER *EATS"] == ""


def test_get_merchant_logo_map_empty_string_when_unmatched(
    small_seed, clear_manual_cache, monkeypatch
):
    monkeypatch.setattr(merchant_logos.logos, "listdir_urls", lambda prefix: {})
    result = merchant_logos.get_merchant_logo_map(["GRENOBLE TABAC LE SAINT C"])
    assert result["GRENOBLE TABAC LE SAINT C"] == ""


def test_get_merchant_logo_map_scans_disk_once_for_n_names(
    small_seed, clear_manual_cache, monkeypatch
):
    """Pas de N+1 : 1 seul appel à listdir_urls quelle que soit la taille de la liste."""
    calls = {"n": 0}

    def counting(prefix):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(merchant_logos.logos, "listdir_urls", counting)
    merchant_logos.get_merchant_logo_map(
        ["A", "B", "C", "HELP.UBER.COM UBER *EATS", "GOOGLE YOUTUBEPR"]
    )
    assert calls["n"] == 1


@override_settings(BRANDFETCH_CLIENT_ID="test-client-id")
def test_brandfetch_url_builds_expected_hotlink():
    url = merchant_logos._brandfetch_url("decathlon.com")
    assert url == (
        "https://cdn.brandfetch.io/domain/decathlon.com/theme/light/w/48/h/48"
        "/fallback/404/icon.png?c=test-client-id"
    )


@override_settings(BRANDFETCH_CLIENT_ID="")
def test_brandfetch_url_empty_without_client_id():
    assert merchant_logos._brandfetch_url("decathlon.com") == ""


@override_settings(BRANDFETCH_CLIENT_ID="test-client-id")
def test_brandfetch_url_empty_for_invalid_domain():
    """Défense en profondeur — is_valid_domain() réutilisé (garde anti-injection URL)."""
    assert merchant_logos._brandfetch_url("https://evil.example/x") == ""


# ── save_manual_logo ──────────────────────────────────────────────────────────


def test_save_manual_logo_delegates_to_fetch_from_url_with_merchant_prefix(monkeypatch):
    captured: dict[str, str] = {}

    def fake_fetch_from_url(url, slug, *, prefix, on_saved):
        captured.update(url=url, slug=slug, prefix=prefix)
        on_saved()
        return f"{prefix}/{slug}.png"

    monkeypatch.setattr(merchant_logos.logos, "fetch_from_url", fake_fetch_from_url)
    name = merchant_logos.save_manual_logo(
        "GRENOBLE TABAC LE SAINT C", "https://x.example/logo.png"
    )

    assert name == "icons/merchants/grenoble-tabac-le-saint-c.png"
    assert captured["prefix"] == "icons/merchants"
    assert captured["slug"] == "grenoble-tabac-le-saint-c"


def test_save_manual_logo_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(
        merchant_logos.logos,
        "fetch_from_url",
        lambda url, slug, *, prefix, on_saved: None,
    )
    assert (
        merchant_logos.save_manual_logo("SOME SHOP", "https://x.example/logo.png")
        is None
    )
