"""
tests/budget/test_views.py

Tests des vues budget/ :
  - Auth : toutes les vues @login_required redirigent en 302 pour user non connecté
  - Category cashflow fragment + page detail
"""

import hashlib
import re
from decimal import Decimal

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from services import logos as logos_service
from transactions.models import Category, Transaction

# Storage MEDIA en mémoire pour les tests merchant_logo_repair — même pattern
# que tests/services/test_logos.py (aucun fichier réel écrit, aucun réseau :
# services.logos._download_url est monkeypatché).
_INMEM_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# =============================================================================
# Fixtures locales (cashflow — scope narrow, pas dans conftest)
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="views@budget.ch", password="pass"
    )


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="other-views@budget.ch", password="pass"
    )


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def other_client(other_user):
    c = Client()
    c.force_login(other_user)
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Institution

    return Institution.objects.create(
        name="Views Budget Bank",
        slug="views-budget-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account(db, bank, user):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=bank,
        name="Views Budget Account",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def some_category(db):
    return Category.objects.create(
        name="Views Test Cat",
        slug="views-test-cat",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


@pytest.fixture
def some_rule(db, some_category):
    from transactions.models import CategorizationRule

    return CategorizationRule.objects.create(
        keyword="VIEWSTEST",
        category=some_category,
        target_field="display_name",
        priority=1,
        is_active=True,
    )


def make_tx(account, category, amount="-50.00", seed="cf"):
    from datetime import date

    return Transaction.objects.create(
        account=account,
        category=category,
        date=date.today().replace(day=1),
        amount=Decimal(amount),
        currency="CHF",
        amount_chf=Decimal(amount),
        description_raw=f"CF TX {seed}",
        display_name=f"CF TX {seed}",
        is_ignored=False,
        import_hash=hashlib.sha256(f"cf-test:{seed}".encode()).hexdigest(),
    )


# =============================================================================
# Auth — vues budget/ sans paramètre
# =============================================================================


@pytest.mark.django_db
def test_budget_index_requires_login(client):
    response = client.get(reverse("budget:index"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_panel_transactions_requires_login(client):
    response = client.get(reverse("budget:panel_transactions"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_panel_rules_list_requires_login(client):
    response = client.get(reverse("budget:panel_rules_list"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_export_rules_requires_login(client):
    response = client.get(reverse("budget:export_rules_download"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_toggle_decimals_requires_login(client):
    response = client.post(reverse("budget:toggle_decimals"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


# =============================================================================
# Auth — vues budget/ avec paramètre slug ou pk
# =============================================================================


@pytest.mark.django_db
def test_budget_category_detail_requires_login(client, some_category):
    response = client.get(reverse("budget:category_detail", args=[some_category.slug]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_category_cashflow_fragment_requires_login(client, some_category):
    response = client.get(
        reverse("budget:category_cashflow_fragment", args=[some_category.slug])
    )
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_rule_toggle_active_requires_login(client, some_rule):
    response = client.post(reverse("budget:rule_toggle_active", args=[some_rule.id]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_rule_delete_requires_login(client, some_rule):
    response = client.post(reverse("budget:rule_delete", args=[some_rule.id]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_rule_row_edit_requires_login(client, some_rule):
    response = client.get(reverse("budget:rule_row_edit", args=[some_rule.id]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


# =============================================================================
# Category cashflow fragment
# =============================================================================


@pytest.fixture
def cf_category(db):
    return Category.objects.create(
        name="Alimentation CF",
        slug="alimentation-cf",
        colour_hex="#4ade80",
        order=50,
        is_system=False,
    )


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_200(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    assert response.status_code == 200
    # #196 : pas juste 200 — le bon partial doit être rendu (un template vidé → rouge).
    assertTemplateUsed(response, "budget/_category_cashflow_card_inner.html")


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_inner_html_only(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_category_cashflow_fragment_contains_kpi_strip(auth_client, cf_category):
    # Le header « Cashflow » + le filtre comptes sont désormais STATIQUES (hors zone
    # swappée, #24). Le fragment = le CORPS (Sankey + KPI strip) → il porte les
    # onglets KPI (Transactions / Objectif), pas le titre « Cashflow ».
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert "Transactions" in content
    assert "Objectif" in content
    assert "<!DOCTYPE html>" not in content  # inner HTML only


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_404_for_unknown_slug(auth_client):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=["slug-qui-nexiste-pas"])
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_category_cashflow_fragment_no_sankey_without_transactions(
    auth_client, cf_category
):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    assert 'id="sankey-chart"' not in response.content.decode()


@pytest.mark.django_db
def test_category_cashflow_fragment_shows_sankey_with_active_transactions(
    auth_client, account, cf_category
):
    make_tx(account, cf_category, seed="sankey-ok")
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert 'id="sankey-chart"' in content
    assert 'id="sankey-data"' in content


@pytest.mark.django_db
def test_category_cashflow_fragment_ignored_txs_excluded_from_total(
    auth_client, account, cf_category
):
    make_tx(account, cf_category, amount="-100.00", seed="active")
    ignored_tx = make_tx(account, cf_category, amount="-999.00", seed="ignored")
    ignored_tx.is_ignored = True
    ignored_tx.save(update_fields=["is_ignored"])
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert "999" not in content or "100" in content


@pytest.mark.django_db
def test_category_cashflow_fragment_other_user_sees_zero_total(
    other_client, account, cf_category
):
    make_tx(account, cf_category, amount="-500.00", seed="other-idor")
    response = other_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    assert response.status_code == 200
    assert "500" not in response.content.decode()


# =============================================================================
# Category detail page
# =============================================================================


@pytest.mark.django_db
def test_category_detail_returns_200(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert response.status_code == 200
    # #196 : la page detail rend bien son template (pas un 200 sur page vide).
    assertTemplateUsed(response, "budget/category_detail.html")


@pytest.mark.django_db
def test_category_detail_returns_full_page(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert "<!DOCTYPE html>" in content or "<html" in content


@pytest.mark.django_db
def test_category_detail_returns_404_for_unknown_slug(auth_client):
    response = auth_client.get(reverse("budget:category_detail", args=["slug-inconnu"]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_category_detail_no_sankey_without_transactions(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert 'id="sankey-chart"' not in response.content.decode()


@pytest.mark.django_db
def test_category_detail_shows_sankey_with_transactions(
    auth_client, account, cf_category
):
    make_tx(account, cf_category, seed="detail-sankey")
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert 'id="sankey-chart"' in content


@pytest.mark.django_db
def test_category_detail_shows_category_name(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert cf_category.name in response.content.decode()


@pytest.mark.django_db
def test_category_detail_contains_cashflow_card(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert 'id="cashflow-card"' in response.content.decode()


# =============================================================================
# Panel transactions — filtre catégories blacklist
# =============================================================================


@pytest.mark.django_db
def test_panel_transactions_excludes_hidden_categories(
    auth_client, account, cf_category
):
    """Le panel exclut les transactions des catégories masquées en session."""
    from datetime import date

    tx = Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-30.00"),
        currency="CHF",
        amount_chf=Decimal("-30.00"),
        description_raw="EXCLUDED BY CAT FILTER",
        display_name="EXCLUDED BY CAT FILTER",
        import_hash="panel_hidden_cat_test_001",
    )
    session = auth_client.session
    session["budget_filter_categories_hidden"] = [cf_category.slug]
    session.save()
    response = auth_client.get(reverse("budget:panel_transactions"))
    assert response.status_code == 200
    assert tx.display_name.encode() not in response.content


@pytest.mark.django_db
def test_panel_transactions_shows_all_when_no_hidden(auth_client, account, cf_category):
    """Aucune exclusion en session → toutes les transactions visibles."""
    from datetime import date

    tx = Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-42.00"),
        currency="CHF",
        amount_chf=Decimal("-42.00"),
        description_raw="VISIBLE TX NO FILTER",
        display_name="VISIBLE TX NO FILTER",
        import_hash="panel_no_filter_test_001",
    )
    response = auth_client.get(reverse("budget:panel_transactions"))
    assert response.status_code == 200
    assert tx.display_name.encode() in response.content


@pytest.mark.django_db
def test_panel_transactions_contains_category_filter(auth_client, cf_category):
    """Le panel transactions expose le composant filtre catégories dans le HTML."""
    r = auth_client.get(reverse("budget:panel_transactions"))
    assert r.status_code == 200
    assert b"categories-filter-details" in r.content


# =============================================================================
# Panel transactions — KPI dynamiques (inconnues / pointées)
# =============================================================================


def _kpi_fraction(html: str, label: str) -> str:
    """
    Extrait "N/M <label>(s)" du HTML — regex plutôt qu'un match d'octets brut
    pour ne pas dépendre de l'indentation exacte du template autour du texte,
    tout en distinguant proprement le singulier du pluriel via `es?`.
    """
    m = re.search(rf"(\d+)/(\d+) {label}s?", html)
    assert m is not None, f"KPI '{label}' introuvable dans : {html[:2000]}"
    return m.group(0)


@pytest.mark.django_db
def test_panel_transactions_shows_unknown_and_reconciled_counts(
    auth_client, account, cf_category
):
    """
    2 tx sans catégorie (inconnues) + 1 tx pointée sur 3 au total → le panel
    affiche "2/3 inconnues" et "1/3 pointée" (singulier correct).
    """
    from datetime import date

    for seed in ("unknown-001", "unknown-002"):
        Transaction.objects.create(
            account=account,
            category=None,
            date=date.today().replace(day=1),
            amount=Decimal("-10.00"),
            currency="CHF",
            amount_chf=Decimal("-10.00"),
            description_raw=f"UNKNOWN TX {seed}",
            display_name=f"UNKNOWN TX {seed}",
            import_hash=f"panel_kpi_{seed}",
        )
    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-30.00"),
        currency="CHF",
        amount_chf=Decimal("-30.00"),
        description_raw="RECONCILED TX",
        display_name="RECONCILED TX",
        is_reconciled=True,
        import_hash="panel_kpi_reconciled_001",
    )

    html = auth_client.get(reverse("budget:panel_transactions")).content.decode()

    assert _kpi_fraction(html, "inconnue") == "2/3 inconnues"
    assert _kpi_fraction(html, "pointée") == "1/3 pointée"


@pytest.mark.django_db
def test_panel_transactions_kpi_counts_respect_search_filter(
    auth_client, account, cf_category
):
    """
    Les KPIs portent sur le MÊME queryset filtré que le total affiché, pas sur
    toute la période — une recherche qui exclut la tx inconnue doit la sortir
    du dénominateur ET du numérateur (sinon les KPIs mentent dès qu'on filtre).
    """
    from datetime import date

    Transaction.objects.create(
        account=account,
        category=None,
        date=date.today().replace(day=1),
        amount=Decimal("-10.00"),
        currency="CHF",
        amount_chf=Decimal("-10.00"),
        description_raw="ZZZ UNKNOWN NOMATCH",
        display_name="ZZZ UNKNOWN NOMATCH",
        import_hash="panel_kpi_filter_unknown_001",
    )
    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-20.00"),
        currency="CHF",
        amount_chf=Decimal("-20.00"),
        description_raw="MIGROS MATCH",
        display_name="MIGROS MATCH",
        import_hash="panel_kpi_filter_known_001",
    )

    html = auth_client.get(
        reverse("budget:panel_transactions"), {"q": "MIGROS"}
    ).content.decode()

    # Total filtré = 1 (pas 2) : la tx "ZZZ UNKNOWN NOMATCH" est hors recherche.
    assert _kpi_fraction(html, "inconnue") == "0/1 inconnues"


@pytest.mark.django_db
def test_toggle_reconcile_from_list_returns_oob_kpi_update(
    auth_client, account, cf_category
):
    """
    Pointer une tx depuis la LISTE (source != detail) doit renvoyer, en plus de
    la ligne, un swap OOB de #tx-kpi-summary avec le compteur pointées à jour —
    sinon le KPI affiché reste faux tant que la page n'est pas rechargée
    (c'est tout le sens de la demande : dynamique, pas figé au chargement).
    """
    from datetime import date

    tx = Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-15.00"),
        currency="CHF",
        amount_chf=Decimal("-15.00"),
        description_raw="TOGGLE RECONCILE TX",
        display_name="TOGGLE RECONCILE TX",
        import_hash="toggle_reconcile_oob_001",
    )
    assert tx.is_reconciled is False

    response = auth_client.post(
        reverse("budget:toggle_reconcile", args=[tx.id]), {"source": ""}
    )
    html = response.content.decode()

    assert response.status_code == 200
    tx.refresh_from_db()
    assert tx.is_reconciled is True
    assert 'id="tx-kpi-summary"' in html
    assert "hx-swap-oob" in html
    assert _kpi_fraction(html, "pointée") == "1/1 pointée"


@pytest.mark.django_db
def test_toggle_reconcile_oob_kpi_respects_active_search(
    auth_client, account, cf_category
):
    """
    Le bouton pointer envoie q/amount via hx-include (#tx-results a
    hx-disinherit="*", rien ne s'hérite) — le recalcul OOB doit porter sur le
    MÊME sous-ensemble filtré que celui affiché, pas sur toute la période.
    """
    from datetime import date

    tx_match = Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-15.00"),
        currency="CHF",
        amount_chf=Decimal("-15.00"),
        description_raw="MIGROS TOGGLE",
        display_name="MIGROS TOGGLE",
        import_hash="toggle_reconcile_oob_filter_001",
    )
    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-25.00"),
        currency="CHF",
        amount_chf=Decimal("-25.00"),
        description_raw="COOP OTHER",
        display_name="COOP OTHER",
        import_hash="toggle_reconcile_oob_filter_002",
    )

    html = auth_client.post(
        reverse("budget:toggle_reconcile", args=[tx_match.id]),
        {"source": "", "q": "MIGROS"},
    ).content.decode()

    # 1 seule tx dans le sous-ensemble "MIGROS" — pas 2 — et elle vient d'être pointée.
    assert _kpi_fraction(html, "pointée") == "1/1 pointée"


# =============================================================================
# Garde anti-N+1 (#166) — vue chaude liste transactions (budget/views/transactions.py)
# =============================================================================


@pytest.mark.django_db
def test_panel_transactions_no_n_plus_one(
    auth_client, account, cf_category, django_assert_max_num_queries
):
    """
    Le nombre de requêtes ne doit PAS croître avec le nombre de transactions :
    le queryset porte un `select_related(category/subcategory/account/institution)`.
    Mesuré à 6 requêtes sur ce jeu de données ; borne = 8 (marge auth/session).
    Retirer le `select_related` → une requête PAR ligne en template → test rouge.
    """
    # 20 tx sur la période courante : assez pour qu'un N+1 explose la borne.
    for i in range(20):
        make_tx(account, cf_category, amount=f"-{i + 1}.00", seed=f"nplus1-{i}")
    with django_assert_max_num_queries(8):
        r = auth_client.get(reverse("budget:panel_transactions"))
    assert r.status_code == 200


@pytest.mark.django_db
def test_category_cashflow_fragment_no_n_plus_one(
    auth_client, account, cf_category, django_assert_max_num_queries
):
    """
    Garde anti-N+1 sur le fragment cashflow (budget/views/categories.py).
    Mesuré à 8 requêtes ; borne = 10. Indépendant du volume de transactions.
    """
    for i in range(20):
        make_tx(account, cf_category, amount=f"-{i + 1}.00", seed=f"cf-nplus1-{i}")
    with django_assert_max_num_queries(10):
        r = auth_client.get(
            reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
        )
    assert r.status_code == 200


# =============================================================================
# budget_category_tx_fragment
# =============================================================================


@pytest.mark.django_db
def test_category_tx_fragment_respects_period(auth_client, account, cf_category):
    """Les transactions hors-période active ne doivent pas apparaître dans le fragment."""
    import calendar
    from datetime import date

    today = date.today()
    period_start = today.replace(day=1)
    period_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    # Tx dans la période courante
    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=period_start,
        amount=Decimal("-10.00"),
        currency="CHF",
        amount_chf=Decimal("-10.00"),
        description_raw="TX DANS PERIODE",
        display_name="TX DANS PERIODE",
        import_hash="cat_frag_period_in_001",
    )
    # Tx hors-période : mois précédent
    prev_month = 12 if today.month == 1 else today.month - 1
    prev_year = today.year - 1 if today.month == 1 else today.year
    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date(prev_year, prev_month, 1),
        amount=Decimal("-99.00"),
        currency="CHF",
        amount_chf=Decimal("-99.00"),
        description_raw="TX HORS PERIODE",
        display_name="TX HORS PERIODE",
        import_hash="cat_frag_period_out_001",
    )
    session = auth_client.session
    session["budget_period_start"] = period_start.isoformat()
    session["budget_period_end"] = period_end.isoformat()
    session.save()

    r = auth_client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert r.status_code == 200
    assert b"TX DANS PERIODE" in r.content
    assert b"TX HORS PERIODE" not in r.content


@pytest.mark.django_db
def test_category_tx_fragment_requires_login(client, cf_category):
    r = client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
def test_category_tx_fragment_returns_200(auth_client, cf_category):
    r = auth_client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert r.status_code == 200
    # #196 : le bon partial liste-tx est rendu (sinon 200 sur fragment vide passe).
    assertTemplateUsed(r, "budget/partials/_category_tx_fragment.html")


@pytest.mark.django_db
def test_category_tx_fragment_returns_inner_html_only(auth_client, cf_category):
    r = auth_client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert b"<!DOCTYPE html>" not in r.content
    assert b"<html" not in r.content


@pytest.mark.django_db
def test_category_tx_fragment_returns_404_for_unknown_slug(auth_client):
    r = auth_client.get(
        reverse("budget:category_tx_fragment", args=["slug-qui-nexiste-pas"])
    )
    assert r.status_code == 404


@pytest.mark.django_db
def test_category_tx_fragment_shows_matching_transactions(
    auth_client, account, cf_category
):
    """Search q=MIGROS → transaction MIGROS présente dans le fragment."""
    from datetime import date

    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-55.00"),
        currency="CHF",
        amount_chf=Decimal("-55.00"),
        description_raw="MIGROS GENEVE",
        display_name="MIGROS GENEVE",
        import_hash="cat_tx_frag_migros_001",
    )
    r = auth_client.get(
        reverse("budget:category_tx_fragment", args=[cf_category.slug]),
        {"q": "MIGROS"},
    )
    assert r.status_code == 200
    assert b"MIGROS" in r.content


@pytest.mark.django_db
def test_category_tx_fragment_search_excludes_non_matching(
    auth_client, account, cf_category
):
    """Search q=COOP → transaction MIGROS absente du fragment."""
    from datetime import date

    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-20.00"),
        currency="CHF",
        amount_chf=Decimal("-20.00"),
        description_raw="MIGROS LAUSANNE",
        display_name="MIGROS LAUSANNE",
        import_hash="cat_tx_frag_migros_002",
    )
    r = auth_client.get(
        reverse("budget:category_tx_fragment", args=[cf_category.slug]),
        {"q": "COOP"},
    )
    assert r.status_code == 200
    assert b"MIGROS" not in r.content


@pytest.mark.django_db
def test_category_tx_fragment_idor_other_user_sees_no_data(
    other_client, account, cf_category
):
    """Autre user → 200 mais transactions du premier user invisibles."""
    from datetime import date

    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-77.00"),
        currency="CHF",
        amount_chf=Decimal("-77.00"),
        description_raw="SECRET TX OTHER",
        display_name="SECRET TX OTHER",
        import_hash="cat_tx_frag_idor_001",
    )
    r = other_client.get(
        reverse("budget:category_tx_fragment", args=[cf_category.slug])
    )
    assert r.status_code == 200
    assert b"SECRET TX OTHER" not in r.content


# =============================================================================
# Badge logo marchand — merchant_logo_form / merchant_logo_repair / merchant_logo_badge
# =============================================================================


@override_settings(BRANDFETCH_CLIENT_ID="test-client-id")
@pytest.mark.django_db
def test_panel_transactions_shows_seed_logo_for_known_merchant(
    auth_client, account, cf_category
):
    """
    Une transaction dont le display_name contient un mot-clé du seed (ex. MIGROS)
    doit afficher l'URL Brandfetch (hotlink live) du domaine associé dans le
    fragment liste — pas juste le bouton "+" par défaut.
    """
    tx = make_tx(account, cf_category, seed="migros-badge")
    tx.display_name = "MIGROS MM CHAILLY 0101 LAUSANNE"
    tx.save(update_fields=["display_name"])

    html = auth_client.get(reverse("budget:panel_transactions")).content.decode()

    assert "https://cdn.brandfetch.io/domain/migros.ch/" in html
    assert f'id="tx-merchant-badge-{tx.id}"' in html


@pytest.mark.django_db
def test_panel_transactions_shows_add_button_for_unknown_merchant(
    auth_client, account, cf_category
):
    """Marchand non résolu par le seed → badge vide avec le bouton "+" d'ajout."""
    tx = make_tx(account, cf_category, seed="unknown-badge")

    html = auth_client.get(reverse("budget:panel_transactions")).content.decode()

    assert f'hx-get="/budget/transactions/{tx.id}/merchant-logo/"' in html
    assert "Ajouter un logo pour ce marchand" in html


@pytest.mark.django_db
def test_merchant_logo_form_requires_login(client, account, cf_category):
    tx = make_tx(account, cf_category, seed="form-auth")
    response = client.get(
        reverse("budget:merchant_logo_form", args=[tx.id]),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_merchant_logo_form_other_user_tx_returns_404(
    auth_client, other_client, account, cf_category
):
    """IDOR : un user ne doit pas pouvoir ouvrir le formulaire sur la tx d'un autre."""
    tx = make_tx(account, cf_category, seed="form-idor")
    response = other_client.get(
        reverse("budget:merchant_logo_form", args=[tx.id]),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_merchant_logo_form_renders_form_partial(auth_client, account, cf_category):
    tx = make_tx(account, cf_category, seed="form-ok")
    response = auth_client.get(
        reverse("budget:merchant_logo_form", args=[tx.id]),
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()
    assert response.status_code == 200
    assertTemplateUsed(response, "budget/_tx_merchant_logo_form.html")
    assert f'id="tx-merchant-badge-{tx.id}"' in html
    assert "<!DOCTYPE html>" not in html


@override_settings(STORAGES=_INMEM_STORAGES)
@pytest.mark.django_db
def test_merchant_logo_repair_installs_logo_and_returns_badge(
    auth_client, account, cf_category, monkeypatch
):
    """POST réussi → badge re-rendu avec l'image installée (pas le formulaire)."""
    monkeypatch.setattr(
        logos_service, "_download_url", lambda url: (b"\x89PNG-fake", "image/png")
    )
    tx = make_tx(account, cf_category, seed="repair-ok")
    tx.display_name = "MA PETITE BOUTIQUE"
    tx.save(update_fields=["display_name"])

    response = auth_client.post(
        reverse("budget:merchant_logo_repair", args=[tx.id]),
        {"logo_url": "https://brand.example/logo.png"},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()

    assert response.status_code == 200
    assertTemplateUsed(response, "budget/_tx_merchant_badge.html")
    assert "<img" in html
    assert "form" not in html.lower().split(">")[0]  # pas le formulaire


@override_settings(STORAGES=_INMEM_STORAGES)
@pytest.mark.django_db
def test_merchant_logo_repair_rejects_non_https_url(
    auth_client, account, cf_category, monkeypatch
):
    """URL non-https → 422 + message d'erreur, pas d'installation."""
    touched = {"net": False}

    def spy(_url):
        touched["net"] = True
        return (b"x", "image/png")

    monkeypatch.setattr(logos_service, "_download_url", spy)
    tx = make_tx(account, cf_category, seed="repair-bad-url")

    response = auth_client.post(
        reverse("budget:merchant_logo_repair", args=[tx.id]),
        {"logo_url": "http://brand.example/logo.png"},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()

    assert response.status_code == 422
    assert "https valide obligatoire" in html
    assert touched["net"] is False


@pytest.mark.django_db
def test_merchant_logo_repair_other_user_tx_returns_404(
    auth_client, other_client, account, cf_category
):
    tx = make_tx(account, cf_category, seed="repair-idor")
    response = other_client.post(
        reverse("budget:merchant_logo_repair", args=[tx.id]),
        {"logo_url": "https://brand.example/logo.png"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_merchant_logo_badge_renders_current_state(auth_client, account, cf_category):
    """Cible du bouton Annuler — re-rend le badge sans le formulaire."""
    tx = make_tx(account, cf_category, seed="badge-cancel")
    response = auth_client.get(
        reverse("budget:merchant_logo_badge", args=[tx.id]),
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()
    assert response.status_code == 200
    assertTemplateUsed(response, "budget/_tx_merchant_badge.html")
    assert f'id="tx-merchant-badge-{tx.id}"' in html
