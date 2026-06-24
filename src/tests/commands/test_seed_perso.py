"""
tests/commands/test_seed_perso.py — seed PERSO de l'admin (#146).

`seed_perso` seede, pour UN user, ses catégories perso + ses règles Finary
(owner=user, is_system=False) puis applique les règles. À vérifier :
  - les objets créés sont bien PERSO scopés owner=user (pas système, pas globaux) ;
  - ISOLATION : un autre user ne les voit pas (for_user(other) → absentes) — SR-001/#213 ;
  - IDÉMPOTENCE : re-run → mêmes counts, zéro doublon ;
  - --dry-run n'écrit rien ; user introuvable → CommandError (bruyant) ;
  - --no-apply ne déclenche pas apply_rules.

Le seed RÉSOUT cat/subcat par slug parmi {système, perso du user}. On amorce donc le
référentiel SYSTÈME réel (via `seed_categories`) — l'état prod avant `seed_perso`.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command

from transactions.management.commands._seed_perso_data import (
    FINARY_RULES,
    PERSO_CATEGORIES,
)
from transactions.models import CategorizationRule, Category, SubCategory

PERSO_EMAIL = "owner@bric.test"


def _run(*args) -> str:
    out = StringIO()
    call_command("seed_perso", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(email=PERSO_EMAIL, password="x")


@pytest.fixture
def system_referential(db):
    """Réferentiel SYSTÈME réel (owner NULL) seedé via `seed_categories` — exactement
    l'état prod avant `seed_perso` (le référentiel système tourne au deploy AVANT le
    seed perso). Garantit que les parents système (`loisirs_divertissements`,
    `besoins_essentiels`…) et les sous-cats système ciblées par les règles existent.
    Les slugs PERSO (streaming, velo, hotels…) sont, eux, créés par le seed lui-même.
    """
    call_command("seed_categories")


# =============================================================================
# Création : tout est PERSO, scopé owner=user
# =============================================================================


@pytest.mark.django_db
def test_seed_creates_personal_categories_and_rules(owner, system_referential):
    _run("--user", PERSO_EMAIL, "--no-apply")

    # Toutes les catégories perso attendues existent, owner=user, is_system=False.
    expected_top = {d.slug for d in PERSO_CATEGORIES if d.parent_slug is None}
    got_top = set(
        Category.objects.for_user(owner)
        .filter(owner=owner, is_system=False)
        .values_list("slug", flat=True)
    )
    assert expected_top <= got_top

    # Les règles existent, owner=user, et pointent une catégorie.
    rules = CategorizationRule.objects.for_user(owner).filter(owner=owner)
    assert rules.count() == len(FINARY_RULES)
    assert all(r.category_id is not None for r in rules)
    # Cible CANONIQUE (Phase 2G) : display_name, pas le brut description_raw.
    assert all(
        r.target_field == CategorizationRule.TargetField.DISPLAY_NAME for r in rules
    )


@pytest.mark.django_db
def test_seed_creates_nothing_system_or_unowned(owner, system_referential):
    """Le seed perso ne crée AUCUNE catégorie/règle système (owner NULL) — il ne touche
    que du perso. (Le système préexiste via la fixture, pas via le seed.)

    Delta before/after (pas d'assertion absolue « zéro règle système ») : robuste même si
    un référentiel système venait à contenir des règles un jour."""
    system_cats_before = Category.objects.unscoped().filter(owner__isnull=True).count()
    system_rules_before = (
        CategorizationRule.objects.unscoped().filter(owner__isnull=True).count()
    )

    _run("--user", PERSO_EMAIL, "--no-apply")

    # Le seed ne crée aucune règle ni catégorie SYSTÈME : les compteurs ne bougent pas.
    assert (
        CategorizationRule.objects.unscoped().filter(owner__isnull=True).count()
        == system_rules_before
    )
    assert (
        Category.objects.unscoped().filter(owner__isnull=True).count()
        == system_cats_before
    )


# =============================================================================
# Isolation inter-user (SR-001 / #213)
# =============================================================================


@pytest.mark.django_db
def test_personal_data_invisible_to_other_user(
    owner, system_referential, django_user_model
):
    other = django_user_model.objects.create_user(email="other@bric.test", password="x")

    _run("--user", PERSO_EMAIL, "--no-apply")

    # Les catégories/règles perso d'owner n'apparaissent JAMAIS dans le scope d'un autre.
    assert not (
        Category.objects.for_user(other).filter(is_system=False, owner=owner).exists()
    )
    assert not CategorizationRule.objects.for_user(other).filter(owner=owner).exists()
    # Et l'autre user n'a aucune règle à lui (le seed ne l'a pas touché).
    assert not CategorizationRule.objects.for_user(other).filter(owner=other).exists()


# =============================================================================
# Idempotence
# =============================================================================


@pytest.mark.django_db
def test_seed_is_idempotent(owner, system_referential):
    _run("--user", PERSO_EMAIL, "--no-apply")
    cats_1 = Category.objects.for_user(owner).filter(owner=owner).count()
    subs_1 = SubCategory.objects.for_user(owner).filter(owner=owner).count()
    rules_1 = CategorizationRule.objects.for_user(owner).filter(owner=owner).count()

    for _ in range(2):
        _run("--user", PERSO_EMAIL, "--no-apply")

    assert Category.objects.for_user(owner).filter(owner=owner).count() == cats_1
    assert SubCategory.objects.for_user(owner).filter(owner=owner).count() == subs_1
    assert (
        CategorizationRule.objects.for_user(owner).filter(owner=owner).count()
        == rules_1
    )


# =============================================================================
# dry-run / erreurs / no-apply
# =============================================================================


@pytest.mark.django_db
def test_dry_run_writes_nothing(owner, system_referential):
    out = _run("--user", PERSO_EMAIL, "--dry-run")

    assert not Category.objects.unscoped().filter(owner=owner).exists()
    assert not CategorizationRule.objects.unscoped().filter(owner=owner).exists()
    assert "dry-run" in out


@pytest.mark.django_db
def test_unknown_user_raises_command_error(db):
    with pytest.raises(CommandError):
        _run("--user", "ghost@nobody.test")


@pytest.mark.django_db
def test_default_user_comes_from_settings(owner, system_referential, settings):
    """Sans --user, le seed cible settings.PERSO_SEED_USER_EMAIL."""
    settings.PERSO_SEED_USER_EMAIL = PERSO_EMAIL

    _run("--no-apply")

    assert CategorizationRule.objects.for_user(owner).filter(owner=owner).exists()


@pytest.mark.django_db
def test_no_apply_skips_apply_rules(owner, system_referential):
    with patch("transactions.management.commands.seed_perso.call_command") as mock_call:
        _run("--user", PERSO_EMAIL, "--no-apply")
    mock_call.assert_not_called()


@pytest.mark.django_db
def test_apply_rules_runs_by_default(owner, system_referential):
    with patch("transactions.management.commands.seed_perso.call_command") as mock_call:
        _run("--user", PERSO_EMAIL)
    # apply_rules appelé une fois, scopé sur l'email du user (#205).
    mock_call.assert_called_once()
    assert mock_call.call_args.args[0] == "apply_rules"
    assert mock_call.call_args.kwargs.get("user") == PERSO_EMAIL
