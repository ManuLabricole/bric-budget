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


def _expected_counts() -> tuple[int, int]:
    """Counts attendus DÉRIVÉS du référentiel committé (pas de nombre magique) :
    ajouter une catégorie au JSON ne casse pas ces tests sans raison."""
    data = json.loads(seed_mod.reference_json_path().read_text(encoding="utf-8"))
    cats = len(data["categories"])
    subs = sum(len(c.get("subcategories", [])) for c in data["categories"])
    return cats, subs


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

    expected_cats, expected_subs = _expected_counts()
    assert Category.objects.count() == expected_cats
    assert SubCategory.objects.count() == expected_subs


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

    expected_cats, expected_subs = _expected_counts()
    assert Category.objects.count() == expected_cats
    assert SubCategory.objects.count() == expected_subs
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


# =============================================================================
# Scoping owner — #149 (Option C) : le référentiel ne seed QUE du système partagé
# =============================================================================


@pytest.mark.django_db
def test_seed_only_creates_shared_system_categories():
    """Tout ce que le seed crée est système partagé : owner NULL, is_system=True."""
    _run()

    assert not Category.objects.filter(owner__isnull=False).exists()
    assert not Category.objects.filter(is_system=False).exists()
    assert not SubCategory.objects.filter(owner__isnull=False).exists()
    assert not SubCategory.objects.filter(is_system=False).exists()


@pytest.mark.django_db
def test_seeded_system_categories_all_have_a_colour():
    """Garde-fou dédié (message clair si ça casse) : toute catégorie système seedée
    a une couleur — sinon les charts/pastilles s'affichent sans couleur."""
    _run()

    sans_couleur = list(
        Category.objects.filter(colour_hex="").values_list("slug", flat=True)
    )
    assert not sans_couleur, f"catégories système sans colour_hex : {sans_couleur}"


@pytest.mark.django_db
def test_seed_does_not_clobber_personal_category_with_same_slug(django_user_model):
    """Une perso (owner=user) de même slug qu'une catégorie système n'est JAMAIS touchée
    par le seed (le scope owner=None garantit la coexistence #137)."""
    user = django_user_model.objects.create_user(email="u@bric.test", password="x")
    # 'alimentation_boissons' est un slug système du référentiel réel committé.
    perso = Category.objects.create(
        slug="alimentation_boissons",
        name="Mes courses à moi",
        owner=user,
        is_system=False,
        colour_hex="#123456",
    )

    _run()

    perso.refresh_from_db()
    assert perso.owner_id == user.pk
    assert perso.name == "Mes courses à moi"  # intacte, jamais écrasée par le seed
    assert perso.is_system is False
    # Le système a bien été créé À CÔTÉ (même slug, owner NULL) — coexistence #137.
    assert Category.objects.filter(
        slug="alimentation_boissons", owner__isnull=True, is_system=True
    ).exists()
    assert Category.objects.filter(slug="alimentation_boissons").count() == 2


@pytest.mark.django_db
def test_committed_reference_has_no_personal_entries():
    """Garde-fou Option C : le référentiel partagé ne contient QUE du système
    (zéro is_system=False). Sinon la migration 0017 le re-capturerait en perso."""
    data = json.loads(seed_mod.reference_json_path().read_text(encoding="utf-8"))
    for c in data["categories"]:
        assert c.get("is_system") is True, (
            f"catégorie perso dans le référentiel : {c['slug']}"
        )
        for s in c.get("subcategories", []):
            assert s.get("is_system") is True, (
                f"sous-cat perso dans le référentiel : {s['slug']}"
            )
