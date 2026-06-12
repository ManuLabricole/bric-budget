"""
tests/commands/test_sync_reference_data.py — commande parapluie référentiels (#126).

C'est LA commande du release deploy (migrate && sync_reference_data) : elle
enchaîne les seeds idempotents (banks → categories), propage --dry-run, et
surtout fait remonter le moindre échec en CommandError (exit ≠ 0) pour que
Railway marque le release FAILED — jamais d'échec avalé.
"""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.institutions_config import KNOWN_INSTITUTIONS
from accounts.models import Institution
from services import logos
from transactions.management.commands import seed_categories as seed_cat_mod
from transactions.models import Category, SubCategory


def _expected_category_counts() -> tuple[int, int]:
    """Dérivé du référentiel committé — pas de nombre magique couplé à sa photo."""
    data = json.loads(seed_cat_mod.reference_json_path().read_text(encoding="utf-8"))
    cats = len(data["categories"])
    subs = sum(len(c.get("subcategories", [])) for c in data["categories"])
    return cats, subs


@pytest.fixture(autouse=True)
def _no_logo_fetch(monkeypatch):
    """seed_institutions déclenche le post_save logo par institution — pas de réseau ici."""
    monkeypatch.setattr(logos, "fetch_logo", lambda *a, **k: None)


def _run(*args) -> str:
    out = StringIO()
    call_command("sync_reference_data", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_full_run_seeds_every_referential():
    out = _run()

    expected_cats, expected_subs = _expected_category_counts()
    assert Institution.objects.count() == len(KNOWN_INSTITUTIONS)
    assert Category.objects.count() == expected_cats
    assert SubCategory.objects.count() == expected_subs
    # Sortie lisible dans les logs Railway : un bandeau par référentiel.
    assert "seed_institutions" in out
    assert "seed_categories" in out


@pytest.mark.django_db
def test_many_runs_are_idempotent():
    """Tournée 6 fois dans la semaine → même état, aucun doublon."""
    for _ in range(3):
        _run()

    expected_cats, expected_subs = _expected_category_counts()
    assert Institution.objects.count() == len(KNOWN_INSTITUTIONS)
    assert Category.objects.count() == expected_cats
    assert SubCategory.objects.count() == expected_subs


@pytest.mark.django_db
def test_dry_run_writes_nothing():
    out = _run("--dry-run")

    assert Institution.objects.count() == 0
    assert Category.objects.count() == 0
    assert "dry-run" in out


@pytest.mark.django_db
def test_failing_seed_raises_command_error(tmp_path, monkeypatch):
    """Un sous-seed qui casse = CommandError qui REMONTE (release FAILED), pas avalé."""
    monkeypatch.setattr(
        seed_cat_mod, "reference_json_path", lambda: tmp_path / "absent.json"
    )

    with pytest.raises(CommandError, match="seed_categories"):
        _run()

    # seed_institutions (passé avant) a pu écrire — mais l'échec est visible, c'est le contrat.
    assert Category.objects.count() == 0
