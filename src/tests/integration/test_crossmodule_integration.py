"""
tests/integration/test_crossmodule_integration.py — chaînes cross-module.

Pourquoi en plus de `test_import_integration.py` (fichier → DB) ?
----------------------------------------------------------------
`test_import_integration.py` couvre UNE frontière : parser → ImportService → DB.
Ici on teste les COMBINAISONS entre modules, là où une régression de frontière
échappe aux tests unitaires :

    1. Catégorisation end-to-end : TransactionDict → règle keyword → catégorie en DB.
    2. Agrégation budget       : transactions → vue budget → cashflow par catégorie.
    3. Valorisation patrimoine : comptes + snapshots → net worth CHF multi-devise.
    4. Isolation multi-user    : SR-001 sur des chaînes complètes (B ne voit pas A).

On fait tourner la VRAIE chaîne (service / vue), pas des unités isolées. Les
données sont construites via les factories (`src/tests/factories/`). Seul boundary
externe mocké : `services.exchange_rates.get_exchange_rate` (réseau / API taux).

⚠️ Aucune donnée bancaire réelle (SR-008) : IBAN/montants générés par les factories.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from patrimoine.services.valuation import current_value, net_worth_series
from tests.factories import (
    AccountFactory,
    BalanceSnapshotFactory,
    CategorizationRuleFactory,
    CategoryFactory,
    UserFactory,
)
from transactions.models import Transaction
from transactions.services import ImportService

# Connectors normalisent leurs lignes en TransactionDict (cf. connectors/base.py).
# On en fabrique directement ici : l'objet du test est la chaîne règle → catégo →
# budget/patrimoine, pas le parsing de fichier (déjà couvert par test_import_integration).
TX_FIELDS_DEFAULTS = {
    "time": None,
    "card_last_four": None,
    "balance_after": None,
}


def make_tx_dict(
    *,
    description: str,
    amount: float,
    currency: str = "CHF",
    on: str = "2026-03-17",
    seed: str | None = None,
) -> dict:
    """Construit un TransactionDict normalisé (sortie de connecteur).

    `import_hash` dérivé de seed (ou description+amount) → unique & stable, comme
    le contrat des parsers (connectors/base.py). display_name == merchant_name au
    moment de l'import (ce que produisent les vrais connecteurs).
    """
    key = seed or f"{description}|{amount}|{on}"
    import_hash = hashlib.sha256(key.encode(), usedforsecurity=False).hexdigest()
    return {
        **TX_FIELDS_DEFAULTS,
        "date": on,
        "amount": amount,
        "currency": currency,
        "description_raw": description,
        "display_name": description,
        "merchant_name": description,
        "import_hash": import_hash,
    }


def _file_hash(label: str) -> str:
    """Hash de fichier distinct par scénario (évite la garde anti-doublon file-level)."""
    return hashlib.sha256(label.encode(), usedforsecurity=False).hexdigest()


# =============================================================================
# 1. Catégorisation end-to-end : règle keyword → catégorie finale en DB
# =============================================================================


@pytest.mark.django_db
def test_rule_keyword_assigns_category_through_import_chain():
    """Happy path : une règle perso « MIGROS » → la tx importée porte cette catégorie.

    Chaîne : TransactionDict → ImportService.run → _find_rule (substring) → DB.
    """
    user = UserFactory()
    account = AccountFactory(members=[user])
    category = CategoryFactory(name="Alimentation", slug="alimentation", owner=user)
    CategorizationRuleFactory(
        keyword="MIGROS", category=category, owner=user, target_field="display_name"
    )

    result = ImportService().run(
        transactions=[make_tx_dict(description="MIGROS LAUSANNE", amount=-42.50)],
        account=account,
        imported_by=user,
        filename="categ.csv",
        file_hash=_file_hash("categ-happy"),
    )

    assert result.count_created == 1
    tx = Transaction.objects.get(account=account)
    assert tx.category == category
    assert tx.categorization_rule is not None
    assert tx.categorization_source == Transaction.CategorizationSource.RULE


@pytest.mark.django_db
def test_no_matching_rule_leaves_category_unassigned():
    """Cas limite : aucune règle ne matche → pas de catégorie « RULE ».

    Sans catégorie système seedée (revenus/inconnu), le défaut est None mais la
    source reste DEFAULT (jamais RULE) → on prouve que _find_rule n'a rien matché.
    """
    user = UserFactory()
    account = AccountFactory(members=[user])
    category = CategoryFactory(slug="loisirs", owner=user)
    CategorizationRuleFactory(keyword="SPOTIFY", category=category, owner=user)

    ImportService().run(
        transactions=[make_tx_dict(description="BOULANGERIE DU COIN", amount=-7.20)],
        account=account,
        imported_by=user,
        filename="categ-nomatch.csv",
        file_hash=_file_hash("categ-nomatch"),
    )

    tx = Transaction.objects.get(account=account)
    assert tx.categorization_rule is None
    assert tx.category != category
    assert tx.categorization_source == Transaction.CategorizationSource.DEFAULT


@pytest.mark.django_db
def test_higher_priority_rule_wins_at_import():
    """Deux règles matchent → la plus prioritaire (priority desc) gagne en DB."""
    user = UserFactory()
    account = AccountFactory(members=[user])
    cat_low = CategoryFactory(slug="cat-low", owner=user)
    cat_high = CategoryFactory(slug="cat-high", owner=user)
    CategorizationRuleFactory(keyword="STORE", category=cat_low, owner=user, priority=1)
    CategorizationRuleFactory(
        keyword="APPLE STORE", category=cat_high, owner=user, priority=10
    )

    ImportService().run(
        transactions=[make_tx_dict(description="APPLE STORE GENEVE", amount=-999.00)],
        account=account,
        imported_by=user,
        filename="categ-prio.csv",
        file_hash=_file_hash("categ-prio"),
    )

    tx = Transaction.objects.get(account=account)
    assert tx.category == cat_high


@pytest.mark.django_db
def test_rule_of_other_user_does_not_categorize_my_import():
    """SR-001 : la règle PERSO de B ne catégorise PAS l'import de A.

    `_load_rules` est scopé `for_user(imported_by)` → seules les règles système ou
    de l'importeur s'appliquent. Sans ce scope, le keyword de B (souvent un nom de
    commerçant) fuitait dans la catégorisation de A.
    """
    user_a = UserFactory()
    user_b = UserFactory()
    account_a = AccountFactory(members=[user_a])
    cat_b = CategoryFactory(slug="cat-de-b", owner=user_b)
    # Règle PERSO de B qui matcherait la description importée par A.
    CategorizationRuleFactory(keyword="COOP", category=cat_b, owner=user_b)

    ImportService().run(
        transactions=[make_tx_dict(description="COOP PRONTO", amount=-15.00)],
        account=account_a,
        imported_by=user_a,
        filename="categ-leak.csv",
        file_hash=_file_hash("categ-leak"),
    )

    tx = Transaction.objects.get(account=account_a)
    assert tx.category != cat_b
    assert tx.categorization_rule is None


# =============================================================================
# 2. Agrégation budget : transactions → vue budget → cashflow par catégorie
# =============================================================================


def _this_month(day: int) -> date:
    """Date dans le mois courant (la vue budget agrège la période = mois en cours)."""
    today = timezone.localdate()
    return today.replace(day=day)


@pytest.mark.django_db
def test_budget_index_aggregates_transactions_by_category(client):
    """Happy path : des tx d'une catégorie → la catégorie apparaît dans le budget.

    Chaîne : Transaction (créées via factory) → vue budget_index (GROUP BY catégorie)
    → HTML rendu qui contient le nom de la catégorie. On rend du HTML → on asserte le
    contenu, pas juste le statut (rules/testing.md).
    """
    user = UserFactory()
    account = AccountFactory(members=[user])
    category = CategoryFactory(
        name="Restaurants BudgetAgg", slug="resto-agg", owner=user
    )
    # Deux dépenses dans le mois courant, même catégorie → agrégées.
    from tests.factories.transactions import TransactionFactory

    TransactionFactory(
        account=account,
        category=category,
        amount=Decimal("-30.00"),
        date=_this_month(5),
    )
    TransactionFactory(
        account=account,
        category=category,
        amount=Decimal("-20.00"),
        date=_this_month(6),
    )

    client.force_login(user)
    response = client.get(reverse("budget:index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Restaurants BudgetAgg" in content


@pytest.mark.django_db
def test_budget_index_excludes_ignored_transactions_from_aggregate(client):
    """Cas limite : une tx is_ignored ne gonfle PAS l'agrégat des dépenses.

    La vue exclut is_ignored=True du queryset agrégé (`expense_categories`). On
    asserte sur l'AGRÉGAT en contexte (pas sur le HTML brut : le nom de catégorie
    apparaît aussi dans le sélecteur de filtres, ce qui rendrait un test HTML faux).
    La catégorie dont l'unique tx est ignorée ne doit pas figurer dans les dépenses.
    """
    from tests.factories.transactions import TransactionFactory

    user = UserFactory()
    account = AccountFactory(members=[user])
    visible_cat = CategoryFactory(name="Visible Cat", slug="visible-cat", owner=user)
    hidden_cat = CategoryFactory(
        name="Hidden Ignored Cat", slug="hidden-cat", owner=user
    )

    TransactionFactory(
        account=account,
        category=visible_cat,
        amount=Decimal("-40.00"),
        date=_this_month(7),
    )
    TransactionFactory(
        account=account,
        category=hidden_cat,
        amount=Decimal("-500.00"),
        date=_this_month(8),
        is_ignored=True,
    )

    client.force_login(user)
    response = client.get(reverse("budget:index"))

    assert response.status_code == 200
    expense_slugs = {
        c["category__slug"] for c in response.context["expense_categories"]
    }
    assert "visible-cat" in expense_slugs
    # La catégorie dont l'unique tx est ignorée n'entre pas dans l'agrégat dépenses.
    assert "hidden-cat" not in expense_slugs
    # KPI total dépenses = seulement la tx visible (la tx ignorée est exclue).
    assert response.context["total_expenses"] == Decimal("-40.00")


@pytest.mark.django_db
def test_budget_index_does_not_show_other_users_categories(client):
    """SR-001 : A ne voit pas les transactions/catégories de B dans son budget."""
    from tests.factories.transactions import TransactionFactory

    user_a = UserFactory()
    user_b = UserFactory()
    account_b = AccountFactory(members=[user_b])
    cat_b = CategoryFactory(name="Cat Secrete De B", slug="cat-secrete-b", owner=user_b)
    TransactionFactory(
        account=account_b,
        category=cat_b,
        amount=Decimal("-77.00"),
        date=_this_month(9),
    )

    client.force_login(user_a)
    response = client.get(reverse("budget:index"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Cat Secrete De B" not in content


# =============================================================================
# 3. Valorisation patrimoine : comptes + snapshots → net worth CHF multi-devise
# =============================================================================


@pytest.mark.django_db
def test_net_worth_sums_chf_and_eur_accounts():
    """Happy path multi-devise : net worth CHF = CHF + EUR converti via le taux.

    Chaîne : 2 comptes (CHF + EUR) + snapshots ancrés → net_worth_series (CHF).
    On mocke get_exchange_rate (boundary) à 0.95 → EUR×0.95 ajouté au CHF.
    """
    user = UserFactory()
    on = date(2026, 3, 17)
    chf_account = AccountFactory(members=[user], currency="CHF")
    eur_account = AccountFactory(members=[user], currency="EUR")

    BalanceSnapshotFactory(
        account=chf_account,
        date=on,
        currency="CHF",
        balance=Decimal("1000.00"),
        balance_chf=Decimal("1000.00"),
    )
    # EUR : balance_chf valorisé (symétrie #118). 2000 EUR × 0.95 = 1900 CHF.
    BalanceSnapshotFactory(
        account=eur_account,
        date=on,
        currency="EUR",
        balance=Decimal("2000.00"),
        balance_chf=Decimal("1900.00"),
    )

    accounts = list(
        type(chf_account)
        .objects.for_user(user)
        .filter(pk__in=[chf_account.pk, eur_account.pk])
    )
    with patch(
        "services.exchange_rates.get_exchange_rate", return_value=Decimal("0.95")
    ):
        series = net_worth_series(accounts, on, on)

    assert series.anchored
    assert series.complete
    assert series.values[0] == Decimal("2900.00")  # 1000 CHF + 1900 CHF (EUR converti)


@pytest.mark.django_db
def test_net_worth_incomplete_when_eur_conversion_missing():
    """Cas limite : un snapshot EUR sans balance_chf (taux manquant) → série incomplète.

    Régression #118 : un compte EUR non valorisé ne doit pas inventer un 0 silencieux.
    `complete=False` signale le trou ; la valeur du jour tombe à 0 pour ce compte.
    """
    user = UserFactory()
    on = date(2026, 3, 17)
    eur_account = AccountFactory(members=[user], currency="EUR")
    # balance_chf NULL = conversion pas encore calculée.
    BalanceSnapshotFactory(
        account=eur_account,
        date=on,
        currency="EUR",
        balance=Decimal("500.00"),
        balance_chf=None,
    )

    accounts = list(type(eur_account).objects.for_user(user))
    series = net_worth_series(accounts, on, on)

    assert series.anchored  # un snapshot existe (ancre présente)
    assert not series.complete  # mais sa valorisation CHF manque
    assert series.values[0] == Decimal("0")


@pytest.mark.django_db
def test_current_value_none_without_snapshot_anchor():
    """Cas limite : compte sans aucun snapshot → valeur inconnue (None), jamais 0."""
    user = UserFactory()
    account = AccountFactory(members=[user], currency="CHF")

    assert current_value(account, date(2026, 3, 17)) is None


@pytest.mark.django_db
def test_net_worth_excludes_other_users_account():
    """SR-001 : le net worth de A scopé for_user n'inclut PAS le compte de B.

    On prouve l'isolation au niveau de la CHAÎNE : un compte ancré de B existe en DB,
    mais comme `for_user(user_a)` ne le ramène pas, sa valeur n'entre pas dans le total.
    """
    user_a = UserFactory()
    user_b = UserFactory()
    on = date(2026, 3, 17)
    account_a = AccountFactory(members=[user_a], currency="CHF")
    account_b = AccountFactory(members=[user_b], currency="CHF")

    BalanceSnapshotFactory(
        account=account_a,
        date=on,
        currency="CHF",
        balance=Decimal("100.00"),
        balance_chf=Decimal("100.00"),
    )
    BalanceSnapshotFactory(
        account=account_b,
        date=on,
        currency="CHF",
        balance=Decimal("9999.00"),
        balance_chf=Decimal("9999.00"),
    )

    accounts_a = list(type(account_a).objects.for_user(user_a))
    series = net_worth_series(accounts_a, on, on)

    assert account_b not in accounts_a  # B est bien hors du périmètre de A
    assert series.values[0] == Decimal("100.00")  # seul le compte de A compte


# =============================================================================
# 4. Multi-user end-to-end : import + lecture scopée (chaîne complète, pas vue isolée)
# =============================================================================


@pytest.mark.django_db
def test_two_users_import_same_payload_isolated_chains():
    """SR-001 : A et B importent le MÊME payload → chacun ne lit que ses tx.

    Chaîne complète : import (ImportService) côté A et côté B sur leur propre compte,
    puis lecture scopée `Transaction.objects.for_user`. Aucun croisement, aucune
    collision (file_hash distinct par compte, import_hash distinct par payload).
    """
    user_a = UserFactory()
    user_b = UserFactory()
    account_a = AccountFactory(members=[user_a])
    account_b = AccountFactory(members=[user_b])

    ImportService().run(
        transactions=[make_tx_dict(description="A-ONLY TX", amount=-11.0, seed="a")],
        account=account_a,
        imported_by=user_a,
        filename="a.csv",
        file_hash=_file_hash("multi-a"),
    )
    ImportService().run(
        transactions=[make_tx_dict(description="B-ONLY TX", amount=-22.0, seed="b")],
        account=account_b,
        imported_by=user_b,
        filename="b.csv",
        file_hash=_file_hash("multi-b"),
    )

    a_txs = Transaction.objects.for_user(user_a)
    b_txs = Transaction.objects.for_user(user_b)

    assert a_txs.count() == 1
    assert b_txs.count() == 1
    assert a_txs.first().description_raw == "A-ONLY TX"
    assert b_txs.first().description_raw == "B-ONLY TX"
    # Croisement nul : aucune tx de B visible par A.
    assert not a_txs.filter(description_raw="B-ONLY TX").exists()
