"""
tests/test_internal_transfer.py

Tests : sync_internal_transfer() + propagation à tous les points de catégorisation.

Pourquoi ces tests sont critiques :
    La règle métier "Virements → ignoré automatiquement" touche 3 endroits du code :
    1. budget_categorize_transaction (categorisation manuelle via picker)
    2. ImportService._build_transaction (import CSV)
    3. apply_rules command (batch recatégorisation)

    Si l'un des trois est oublié, les virements apparaissent dans les totaux budgétaires
    et faussent tous les KPIs. Ces tests garantissent la cohérence.

Scénarios testés :
    A. sync_internal_transfer() — unité
        1. Catégorie virements → les deux flags True
        2. Autre catégorie → les deux flags False
        3. Déjà à jour → retourne liste vide (pas de update_fields inutile)
        4. Catégorie None → is_internal=False (pas de catégorie = pas de virement)

    B. budget_categorize_transaction — vue HTTP
        5. Catégoriser → virements → is_ignored=True, is_internal_transfer=True
        6. Catégoriser → virements puis → autre → les deux flags remis à False
        7. Toggle is_ignored manuel (toggle_ignore view) → is_internal_transfer inchangé

    C. ImportService — import CSV
        8. Transaction matchée par règle → virements → is_ignored=True à l'import
        9. Transaction non matchée → catégorie revenue → is_ignored=False (défaut)

    D. apply_rules command
       10. Règle matche, catégorie = virements → is_ignored=True, is_internal_transfer=True
       11. Règle matche, catégorie normale → flags inchangés (False)
"""

import hashlib

import pytest
from django.test import Client
from django.urls import reverse

from transactions.management.commands.apply_rules import Command as ApplyRulesCommand
from transactions.models import CategorizationRule, Category, Transaction  # noqa: E501
from transactions.services import sync_internal_transfer

# =============================================================================
# Fixtures communes
# =============================================================================


@pytest.fixture
def cat_virements(db):
    return Category.objects.create(
        name="Virements",
        slug="virements",
        colour_hex="#5abdc5",
        order=99,
        is_system=True,
    )


@pytest.fixture
def cat_alim(db):
    return Category.objects.create(
        name="Alimentation",
        slug="alimentation_test",
        colour_hex="#aaa",
        order=50,
        is_system=False,
    )


@pytest.fixture
def account(db):
    from accounts.models import Account, Bank

    bank = Bank.objects.create(
        name="Test Bank",
        slug="test-bank-intl",
        country="CH",
        default_currency="CHF",
    )
    return Account.objects.create(
        bank=bank,
        name="Test Account",
        account_type="checking",
        currency="CHF",
    )


def make_tx(account, display_name, category=None, seed=None):
    return Transaction.objects.create(
        account=account,
        date="2026-01-15",
        amount=-10,
        currency="CHF",
        amount_chf=-10,
        description_raw=display_name,
        display_name=display_name,
        category=category,
        import_hash=hashlib.sha256(
            f"intl-test:{seed or display_name}".encode()
        ).hexdigest(),
    )


# =============================================================================
# A. sync_internal_transfer() — unité
# =============================================================================


@pytest.mark.django_db
def test_sync_internal_virements_sets_both_flags_true(cat_virements, account):
    """
    sync_internal_transfer sur une tx catégorisée en "virements"
    → is_internal_transfer=True, is_ignored=True.
    """
    tx = make_tx(account, "VIREMENT CIC", category=cat_virements)
    tx.is_internal_transfer = False
    tx.is_ignored = False

    changed = sync_internal_transfer(tx)

    assert tx.is_internal_transfer is True
    assert tx.is_ignored is True
    assert "is_internal_transfer" in changed
    assert "is_ignored" in changed


@pytest.mark.django_db
def test_sync_internal_other_category_sets_both_flags_false(cat_alim, account):
    """
    sync_internal_transfer sur une tx catégorisée en autre chose
    → is_internal_transfer=False, is_ignored=False.
    """
    tx = make_tx(account, "MIGROS", category=cat_alim)
    tx.is_internal_transfer = True  # état précédent (ex: était un virement)
    tx.is_ignored = True

    changed = sync_internal_transfer(tx)

    assert tx.is_internal_transfer is False
    assert tx.is_ignored is False
    assert "is_internal_transfer" in changed
    assert "is_ignored" in changed


@pytest.mark.django_db
def test_sync_internal_already_up_to_date_returns_empty(cat_virements, account):
    """
    Si les flags sont déjà au bon état, sync_internal_transfer
    ne retourne aucun champ → évite un save() inutile.
    """
    tx = make_tx(account, "VIREMENT YUH→CIC", category=cat_virements)
    tx.is_internal_transfer = True
    tx.is_ignored = True

    changed = sync_internal_transfer(tx)

    assert changed == []


@pytest.mark.django_db
def test_sync_internal_no_category_is_not_internal(account):
    """
    Pas de catégorie → is_internal=False.
    Une transaction sans catégorie n'est jamais un virement interne.
    """
    tx = make_tx(account, "INCONNU")
    tx.is_internal_transfer = False
    tx.is_ignored = False

    changed = sync_internal_transfer(tx)

    assert tx.is_internal_transfer is False
    assert tx.is_ignored is False
    assert changed == []


# =============================================================================
# B. budget_categorize_transaction — vue HTTP
# =============================================================================


@pytest.fixture
def test_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    # CustomUser utilise email comme identifiant unique (pas username).
    return User.objects.create_user(email="test@bricbudget.ch", password="pass")


@pytest.fixture
def auth_client(test_user):
    c = Client()
    c.login(email="test@bricbudget.ch", password="pass")
    return c


@pytest.mark.django_db
def test_categorize_to_virements_sets_internal_flags(
    auth_client, test_user, cat_virements, account
):
    """
    Via la vue budget_categorize_transaction :
    catégoriser une tx en "Virements" → is_internal_transfer=True, is_ignored=True.
    """
    account.members.add(test_user)
    tx = make_tx(account, "TRANSFERT EMMANUEL BARRIOL", seed="t1")

    auth_client.post(
        reverse("budget:categorize"),
        {"tx_id": tx.id, "category_id": cat_virements.id},
    )

    tx.refresh_from_db()
    assert tx.is_internal_transfer is True
    assert tx.is_ignored is True
    assert tx.categorization_source == "manual"


@pytest.mark.django_db
def test_categorize_away_from_virements_resets_flags(
    auth_client, test_user, cat_virements, cat_alim, account
):
    """
    Tx déjà en virements (flags=True) → recatégoriser en Alimentation
    → les deux flags repassent à False.
    """
    account.members.add(test_user)
    tx = make_tx(account, "TRANSFERT", category=cat_virements, seed="t2")
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])

    auth_client.post(
        reverse("budget:categorize"),
        {"tx_id": tx.id, "category_id": cat_alim.id},
    )

    tx.refresh_from_db()
    assert tx.is_internal_transfer is False
    assert tx.is_ignored is False


@pytest.mark.django_db
def test_manual_toggle_ignore_does_not_change_internal_transfer_flag(
    auth_client, test_user, cat_virements, account
):
    """
    Le toggle manuel "Inclure dans l'analyse budgétaire" (toggle_ignore view)
    NE doit PAS modifier is_internal_transfer.
    Invariant : is_internal_transfer = booléen catégorie, pas du toggle manuel.
    """
    account.members.add(test_user)
    tx = make_tx(account, "VIREMENT INTERNE", category=cat_virements, seed="t3")
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])

    # L'utilisateur ré-active la transaction manuellement (toggle ignore)
    auth_client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "list"},
    )

    tx.refresh_from_db()
    # is_ignored a changé (toggle)
    assert tx.is_ignored is False
    # MAIS is_internal_transfer reste True (c'est toujours un virement interne)
    assert tx.is_internal_transfer is True


# =============================================================================
# C. ImportService — import CSV
# =============================================================================


@pytest.mark.django_db
def test_import_virements_category_sets_ignored_at_import(cat_virements, account):
    """
    ImportService._build_transaction avec une règle qui mappe → virements :
    la transaction créée doit avoir is_ignored=True et is_internal_transfer=True.
    Simule ce qui se passe pendant un import CSV réel.
    """
    from transactions.services import ImportService

    rule = CategorizationRule.objects.create(
        keyword="VIREMENT",
        category=cat_virements,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    rules = [rule]

    service = ImportService()
    tx_dict = {
        "display_name": "VIREMENT YUH CIC",
        "description_raw": "VIREMENT YUH CIC",
        "merchant_name": "VIREMENT YUH CIC",
        "amount": "-500",
        "currency": "CHF",
        "date": "2026-01-15",
        "time": None,
        "import_hash": hashlib.sha256(b"import-test-virement").hexdigest(),
    }

    tx_obj = service._build_transaction(
        tx_dict,
        account=account,
        cards_by_last_four={},
        rules=rules,
        default_income_category=None,
        default_unknown_category=None,
    )

    assert tx_obj.is_internal_transfer is True
    assert tx_obj.is_ignored is True
    assert tx_obj.category == cat_virements


@pytest.mark.django_db
def test_import_non_virements_category_does_not_set_ignored(cat_alim, account):
    """
    ImportService avec une règle → Alimentation :
    is_ignored et is_internal_transfer restent False (défaut).
    """
    from transactions.services import ImportService

    rule = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_alim,
        target_field="display_name",
        priority=1,
        is_active=True,
    )

    service = ImportService()
    tx_dict = {
        "display_name": "MIGROS LAUSANNE",
        "description_raw": "MIGROS LAUSANNE",
        "merchant_name": "MIGROS LAUSANNE",
        "amount": "-25",
        "currency": "CHF",
        "date": "2026-01-15",
        "time": None,
        "import_hash": hashlib.sha256(b"import-test-migros").hexdigest(),
    }

    tx_obj = service._build_transaction(
        tx_dict,
        account=account,
        cards_by_last_four={},
        rules=[rule],
        default_income_category=None,
        default_unknown_category=None,
    )

    assert tx_obj.is_internal_transfer is False
    assert tx_obj.is_ignored is False


# =============================================================================
# D. apply_rules command
# =============================================================================


def run_apply_rules():
    from io import StringIO

    cmd = ApplyRulesCommand()
    cmd.stdout = StringIO()
    cmd.handle(dry_run=False, limit=None, reset=False)


@pytest.mark.django_db
def test_apply_rules_virements_rule_sets_ignored(cat_virements, account):
    """
    apply_rules : une règle matche et catégorise en "virements"
    → is_ignored=True, is_internal_transfer=True sauvegardés en DB.
    """
    CategorizationRule.objects.create(
        keyword="VIREMENT",
        category=cat_virements,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_tx(account, "VIREMENT MENSUEL", seed="ar1")
    assert tx.is_ignored is False
    assert tx.is_internal_transfer is False

    run_apply_rules()

    tx.refresh_from_db()
    assert tx.is_ignored is True
    assert tx.is_internal_transfer is True
    assert tx.categorization_source == "rule"


@pytest.mark.django_db
def test_apply_rules_non_virements_rule_does_not_set_ignored(cat_alim, account):
    """
    apply_rules : règle matche → Alimentation.
    is_ignored et is_internal_transfer restent False.
    """
    CategorizationRule.objects.create(
        keyword="COOP",
        category=cat_alim,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_tx(account, "COOP GENEVE", seed="ar2")

    run_apply_rules()

    tx.refresh_from_db()
    assert tx.is_ignored is False
    assert tx.is_internal_transfer is False
    assert tx.category == cat_alim


@pytest.mark.django_db
def test_apply_rules_changing_from_virements_to_other_resets_flags(
    cat_virements, cat_alim, account
):
    """
    Tx précédemment marquée virement interne (is_internal=True, is_ignored=True).
    Une nouvelle règle active catégorise maintenant en Alimentation.
    apply_rules doit remettre les deux flags à False.
    """
    # Règle active : → Alimentation
    CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_alim,
        target_field="display_name",
        priority=5,
        is_active=True,
    )
    # Tx avec anciens flags virement (ex: ancienne règle supprimée)
    tx = make_tx(account, "MIGROS LAUSANNE", seed="ar3")
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])

    run_apply_rules()

    tx.refresh_from_db()
    assert tx.is_internal_transfer is False
    assert tx.is_ignored is False
    assert tx.category == cat_alim


# =============================================================================
# E. Template rendering — badge "Classifiée comme mouvement interne"
# =============================================================================


@pytest.mark.django_db
def test_panel_tx_detail_shows_badge_when_internal_transfer(cat_virements, account):
    """
    Quand is_internal_transfer=True, le template _panel_tx_detail.html doit
    afficher le badge "Classifiée comme mouvement interne".
    Ce badge explique visuellement pourquoi le toggle "Inclure" est désactivé.
    """
    from django.template.loader import render_to_string

    tx = make_tx(account, "VIREMENT YUH → CIC", category=cat_virements)
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])

    html = render_to_string(
        "budget/_panel_tx_detail.html",
        {"tx": tx, "bank_icon_url": "", "close_on_back": False, "source": "detail"},
    )

    assert "Classifiée comme mouvement interne" in html


@pytest.mark.django_db
def test_panel_tx_detail_no_badge_when_not_internal_transfer(cat_alim, account):
    """
    Quand is_internal_transfer=False, le badge ne doit PAS apparaître —
    pas de bruit visuel pour les transactions normales.
    """
    from django.template.loader import render_to_string

    tx = make_tx(account, "MIGROS LAUSANNE", category=cat_alim)
    tx.is_internal_transfer = False
    tx.is_ignored = False
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])

    html = render_to_string(
        "budget/_panel_tx_detail.html",
        {"tx": tx, "bank_icon_url": "", "close_on_back": False, "source": "detail"},
    )

    assert "Classifiée comme mouvement interne" not in html


# =============================================================================
# F. Reload page — toggle ignore depuis le panneau détail en contexte category
# =============================================================================


@pytest.mark.django_db
def test_toggle_ignore_from_detail_close_on_back_returns_redirect(
    auth_client, test_user, cat_alim, account
):
    """
    Quand toggle_ignore est appelé avec source=detail et close_on_back=true
    (ouvert depuis category_detail), la réponse doit être un HX-Redirect
    pour recharger la page entière (Sankey + KPIs + liste).

    Sans reload complet, le Sankey et les KPIs restent figés après toggle.
    """
    account.members.add(test_user)
    tx = make_tx(account, "MIGROS", category=cat_alim, seed="oob1")
    tx.is_ignored = False
    tx.save(update_fields=["is_ignored"])

    response = auth_client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "detail", "close_on_back": "true"},
        HTTP_HX_CURRENT_URL="/budget/categorie/alimentation/",
    )

    assert response.status_code == 200
    assert response.has_header("HX-Redirect")
    assert response["HX-Redirect"] == "/budget/categorie/alimentation/"


@pytest.mark.django_db
def test_toggle_ignore_from_detail_no_oob_when_not_close_on_back(
    auth_client, test_user, cat_alim, account
):
    """
    Depuis le panneau principal (close_on_back=false), pas d'OOB —
    la liste panel est rechargée séparément.
    """
    account.members.add(test_user)
    tx = make_tx(account, "MIGROS", category=cat_alim, seed="oob2")

    response = auth_client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "detail", "close_on_back": "false"},
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "hx-swap-oob" not in content
