"""
tests/commands/test_apply_rules.py

Ce qu'on teste : la commande apply_rules.

Scénarios critiques :
1. Une règle matche → transaction mise à jour (category + source)
2. Categorization manuelle → jamais écrasée (invariant fondamental)
3. --reset remet category=None avant de réappliquer
4. Plusieurs règles matchent → la plus haute priorité gagne
5. Aucune règle ne matche → transaction inchangée

On appelle Command().handle() directement pour éviter subprocess.
C'est plus rapide et donne accès aux exceptions sans parsing de stderr.

Pourquoi tester la commande et pas juste _find_rule() ?
_find_rule() est déjà couvert par test_categorization_priority.py.
Ici on teste l'intégration : la commande charge les règles depuis la DB,
parcourt les transactions, et écrit les bons champs.
"""

from io import StringIO

import pytest

from transactions.management.commands.apply_rules import Command
from transactions.models import CategorizationRule, Category, Transaction

# =============================================================================
# Fixtures — catégories + règles + transactions
# =============================================================================


@pytest.fixture
def cat_alim(db):
    return Category.objects.create(
        name="Alimentation",
        slug="test-alim",
        colour_hex="#aaa",
        order=50,
        is_system=False,
    )


@pytest.fixture
def cat_transport(db):
    return Category.objects.create(
        name="Transport",
        slug="test-transport",
        colour_hex="#bbb",
        order=51,
        is_system=False,
    )


@pytest.fixture
def account(db):
    """Compte minimal pour attacher les transactions."""
    from accounts.models import Account, Institution

    bank = Institution.objects.create(
        name="Test Bank",
        slug="test-bank-apply",
        country="CH",
        default_currency="CHF",
    )
    return Account.objects.create(
        institution=bank,
        name="Test Account",
        account_type="checking",
        currency="CHF",
    )


def make_transaction(account, display_name, source="default", category=None, seed=None):
    """Crée une transaction minimale en DB."""
    import hashlib

    hash_seed = seed or display_name
    return Transaction.objects.create(
        account=account,
        date="2026-01-15",
        amount=-10,
        currency="CHF",
        amount_chf=-10,
        description_raw=display_name,
        display_name=display_name,
        categorization_source=source,
        category=category,
        import_hash=hashlib.sha256(f"apply-test:{hash_seed}".encode()).hexdigest(),
    )


def run_command(*args):
    """Lance la commande avec les options données et retourne le stdout."""
    cmd = Command()
    cmd.style = cmd.style  # garde le style par défaut
    out = StringIO()
    cmd.stdout = out  # type: ignore[assignment]

    options = {
        "dry_run": "--dry-run" in args,
        "limit": None,
        "reset": "--reset" in args,
    }
    cmd.handle(**options)
    return out.getvalue()


# =============================================================================
# 1. Règle matche → transaction mise à jour
# =============================================================================


@pytest.mark.django_db
def test_matching_rule_updates_transaction(cat_alim, account):
    """
    Une règle 'MONOPRIX' → Alimentation.
    Transaction display_name = 'MONOPRIX GRENOBLE'.
    Après apply_rules, la transaction doit avoir category=Alimentation, source='rule'.
    """
    CategorizationRule.objects.create(
        keyword="MONOPRIX",
        category=cat_alim,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_transaction(account, "MONOPRIX GRENOBLE")

    run_command()

    tx.refresh_from_db()
    assert tx.category == cat_alim
    assert tx.categorization_source == "rule"
    assert tx.categorization_rule is not None
    assert tx.categorization_rule.keyword == "MONOPRIX"


# =============================================================================
# 2. Catégorisation manuelle → jamais écrasée
# =============================================================================


@pytest.mark.django_db
def test_manual_categorization_never_overwritten(cat_alim, cat_transport, account):
    """
    Transaction avec source='manual' et category=Transport.
    Une règle matche son display_name → Alimentation.
    La règle NE DOIT PAS écraser le choix manuel.
    """
    CategorizationRule.objects.create(
        keyword="SNCF",
        category=cat_alim,  # intentionnellement mauvaise cat pour le test
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_transaction(
        account,
        "SNCF BILLET PARIS",
        source="manual",
        category=cat_transport,
    )

    run_command()

    tx.refresh_from_db()
    assert tx.category == cat_transport, (
        "La catégorisation manuelle doit être préservée"
    )
    assert tx.categorization_source == "manual"


# =============================================================================
# 3. --reset : remet à zéro avant de réappliquer
# =============================================================================


@pytest.mark.django_db
def test_reset_clears_then_reapplies(cat_alim, cat_transport, account):
    """
    Transaction déjà catégorisée en 'rule' → Transport.
    On crée une nouvelle règle → Alimentation (plus haute priorité).
    --reset doit remettre à zéro, puis réappliquer → Alimentation gagne.
    """
    # Ancienne règle (déjà appliquée manuellement pour simuler un état existant)
    CategorizationRule.objects.create(
        keyword="UBER",
        category=cat_transport,
        target_field="display_name",
        priority=1,
        is_active=False,  # désactivée — ne doit pas gagner
    )
    # Nouvelle règle active avec priorité plus haute
    rule_new = CategorizationRule.objects.create(
        keyword="UBER",
        category=cat_alim,
        target_field="display_name",
        priority=2,
        is_active=True,
    )
    # Transaction déjà catégorisée (source=rule, cat=transport)
    tx = make_transaction(
        account,
        "UBER EATS PARIS",
        source="rule",
        category=cat_transport,
    )

    run_command("--reset")

    tx.refresh_from_db()
    assert tx.category == cat_alim, "La nouvelle règle active doit gagner après reset"
    assert tx.categorization_source == "rule"
    assert tx.categorization_rule == rule_new


# =============================================================================
# 4. Priorité — la règle la plus haute gagne
# =============================================================================


@pytest.mark.django_db
def test_highest_priority_rule_wins(cat_alim, cat_transport, account):
    """
    Deux règles matchent 'MIGROS' :
    - p1 → Transport (basse priorité)
    - p2 → Alimentation (haute priorité)
    Après apply_rules, c'est Alimentation qui gagne.
    """
    CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_transport,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    rule_high = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_alim,
        target_field="display_name",
        priority=2,
        is_active=True,
    )
    tx = make_transaction(account, "MIGROS LAUSANNE")

    run_command()

    tx.refresh_from_db()
    assert tx.category == cat_alim
    assert tx.categorization_rule == rule_high


# =============================================================================
# 5. Aucune règle ne matche → transaction inchangée
# =============================================================================


@pytest.mark.django_db
def test_no_matching_rule_leaves_transaction_unchanged(cat_alim, account):
    """
    Règle 'COOP' → Alimentation.
    Transaction display_name = 'MIGROS' → aucune règle ne matche.
    La transaction doit rester source='default', category=None.
    """
    CategorizationRule.objects.create(
        keyword="COOP",
        category=cat_alim,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_transaction(account, "MIGROS LAUSANNE")
    assert tx.category is None

    run_command()

    tx.refresh_from_db()
    assert tx.category is None
    assert tx.categorization_source == "default"


# =============================================================================
# 6. Dry-run → rien en DB
# =============================================================================


@pytest.mark.django_db
def test_dry_run_does_not_write(cat_alim, account):
    """
    --dry-run : la commande affiche ce qu'elle ferait mais n'écrit pas en DB.
    La transaction doit rester inchangée après le dry-run.
    """
    CategorizationRule.objects.create(
        keyword="DECATHLON",
        category=cat_alim,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_transaction(account, "DECATHLON GRENOBLE")

    output = run_command("--dry-run")

    tx.refresh_from_db()
    assert tx.category is None, "Dry-run ne doit rien écrire en DB"
    assert "dry run" in output.lower()
    assert "DECATHLON" in output
