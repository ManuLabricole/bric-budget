"""
tests/commands/test_seed_categories.py — seed du référentiel catégories (#126).

Le référentiel est committé (src/reference/categories.json) et le seed doit être
prod-safe : idempotent (N runs = même état), delta minimal quand le JSON change,
échec BRUYANT (CommandError → exit ≠ 0, le release Railway doit le voir),
--dry-run sans écriture. C'est la commande qui tourne à chaque deploy via
sync_reference_data.
"""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from transactions.management.commands import seed_categories as seed_mod
from transactions.models import Category, SubCategory


def _run(*args) -> str:
    out = StringIO()
    call_command("seed_categories", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def tiny_reference(tmp_path, monkeypatch):
    """Référentiel minimal contrôlé — pour les scénarios de mutation/erreur."""
    data = {
        "categories": [
            {
                "slug": "transport",
                "name": "Transport",
                "icon": "auto-transport",
                "colour_hex": "#aabbcc",
                "order": 1,
                "is_system": True,
                "is_active": True,
                "subcategories": [
                    {
                        "slug": "carburant",
                        "name": "Carburant",
                        "icon": "fuel",
                        "default_nature": "variable_mandatory",
                        "is_system": True,
                        "is_active": True,
                    },
                    {
                        "slug": "vieux-truc",
                        "name": "Vieux truc",
                        "default_nature": "neutral",
                        "is_active": False,
                    },
                ],
            }
        ]
    }
    path = tmp_path / "categories.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(seed_mod, "reference_json_path", lambda: path)
    return path


# =============================================================================
# Référentiel réel committé (celui que la prod consommera)
# =============================================================================


@pytest.mark.django_db
def test_seed_real_reference_creates_everything():
    _run()

    # Le référentiel committé : 17 catégories / 122 sous-catégories (audit 2026-06-12).
    assert Category.objects.count() == 17
    assert SubCategory.objects.count() == 122


@pytest.mark.django_db
def test_seed_real_reference_is_idempotent_over_many_runs():
    """Tournée 6 fois dans la semaine → ne change que ce qui doit l'être (= rien ici)."""
    _run()
    snapshot = list(
        Category.objects.order_by("slug").values(
            "slug", "name", "colour_hex", "order", "is_active", "is_system"
        )
    )

    for _ in range(3):
        _run()

    assert Category.objects.count() == 17
    assert SubCategory.objects.count() == 122
    assert (
        list(
            Category.objects.order_by("slug").values(
                "slug", "name", "colour_hex", "order", "is_active", "is_system"
            )
        )
        == snapshot
    )


# =============================================================================
# Scénarios de vie du référentiel (JSON contrôlé)
# =============================================================================


@pytest.mark.django_db
def test_seed_syncs_fields_including_is_active_and_icon(tiny_reference):
    _run()

    cat = Category.objects.get(slug="transport")
    assert cat.name == "Transport"
    assert cat.colour_hex == "#aabbcc"
    assert cat.is_active is True
    sub = SubCategory.objects.get(slug="carburant")
    assert sub.icon == "fuel"
    assert sub.default_nature == "variable_mandatory"
    # is_active arrive du JSON — une sous-catégorie retirée du référentiel actif
    # doit être désactivée en DB (zéro drift).
    assert SubCategory.objects.get(slug="vieux-truc").is_active is False


@pytest.mark.django_db
def test_seed_applies_only_the_delta_on_change(tiny_reference):
    """« Dans un mois j'ajoute/modifie une catégorie » → le deploy applique SEUL ce delta."""
    _run()
    untouched_sub = SubCategory.objects.get(slug="carburant")

    data = json.loads(tiny_reference.read_text())
    data["categories"][0]["name"] = "Transports & Mobilité"
    data["categories"][0]["colour_hex"] = "#112233"
    data["categories"][0]["subcategories"].append(
        {"slug": "velo", "name": "Vélo", "default_nature": "variable_discretionary"}
    )
    tiny_reference.write_text(json.dumps(data), encoding="utf-8")

    _run()

    cat = Category.objects.get(slug="transport")
    assert cat.name == "Transports & Mobilité"
    assert cat.colour_hex == "#112233"
    assert SubCategory.objects.filter(slug="velo").exists()
    # Le reste n'a pas bougé.
    assert SubCategory.objects.get(slug="carburant").pk == untouched_sub.pk
    assert SubCategory.objects.get(slug="carburant").name == "Carburant"


@pytest.mark.django_db
def test_seed_restores_manual_db_drift(tiny_reference):
    _run()
    Category.objects.filter(slug="transport").update(colour_hex="#000000")

    _run()

    assert Category.objects.get(slug="transport").colour_hex == "#aabbcc"


@pytest.mark.django_db
def test_neutral_default_nature_becomes_empty(tiny_reference):
    """Compat JSON historique : "neutral" n'est pas un choix du modèle → ""."""
    _run()

    assert SubCategory.objects.get(slug="vieux-truc").default_nature == ""


# =============================================================================
# Modes d'échec et dry-run (ce que le release Railway doit voir)
# =============================================================================


@pytest.mark.django_db
def test_missing_file_raises_command_error(tmp_path, monkeypatch):
    """⛔ Fini l'échec silencieux exit 0 : fichier absent = CommandError (release FAILED)."""
    monkeypatch.setattr(seed_mod, "reference_json_path", lambda: tmp_path / "nope.json")

    with pytest.raises(CommandError):
        _run()

    assert Category.objects.count() == 0


@pytest.mark.django_db
def test_dry_run_writes_nothing(tiny_reference):
    out = _run("--dry-run")

    assert Category.objects.count() == 0
    assert SubCategory.objects.count() == 0
    assert "dry-run" in out
