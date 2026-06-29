"""
tests/patrimoine/test_account_detail_view.py — Vue page zoom compte (#82 PR C).

Couvre :
  - GET page : 200, graphe mono-compte (json_script), liste tx, panneau Détails.
  - IDOR (SR-001) : compte d'autrui → 404 sur page + toutes les sous-routes.
  - Type de compte LECTURE SEULE (affiché, pas d'input/form pour le muter).
  - Période : POST → session, courbe re-rendue (HTMX swap du corps).
  - Édition inline IBAN  : GET form · POST valide (sync Account+Checking) · POST invalide (422) · doublon.
  - Édition inline BIC   : POST valide · POST invalide (422).
  - Édition inline Taux  : POST valide (SavingsAccount) · POST invalide (422).
  - Garde : champ non éditable pour le type (URL forgée) → 404.

Fixtures locales : savings_account, other_user (IDOR), make_checking.
"""

import pytest
from django.urls import reverse

from accounts.models import Account, CheckingAccount, SavingsAccount


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="intruder@test.ch", password="pass"
    )


@pytest.fixture
def checking_details(db, chf_account):
    """CheckingAccount rattaché au compte courant CHF de la conftest.

    IBAN posé sur Account.iban (source unique #82) ; CheckingAccount ne porte
    plus que le BIC.
    """
    chf_account.iban = "CH5604835012345678009"
    chf_account.save(update_fields=["iban"])
    return CheckingAccount.objects.create(account=chf_account, bic="YUHHCHZZ")


@pytest.fixture
def savings_account(db, chf_institution, user):
    acc = Account.objects.create(
        institution=chf_institution,
        name="CHF Livret",
        account_type="savings",
        currency="CHF",
    )
    acc.members.add(user)
    SavingsAccount.objects.create(account=acc, interest_rate="1.50")
    return acc


# ── GET page ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_account_detail_get_renders_chart_tx_and_details(
    client_logged, chf_account, checking_details, make_snapshot, make_tx
):
    """Page : graphe mono-compte (json_script), liste tx, panneau Détails éditable."""
    make_snapshot(chf_account, "2026-06-01", balance=1000, balance_chf=1000)
    make_tx(chf_account, "2026-06-08", amount=-30)

    resp = client_logged.get(
        reverse("patrimoine:account_detail", args=[chf_account.pk])
    )
    html = resp.content.decode()

    assert resp.status_code == 200
    assert chf_account.name in html
    # Graphe mono-compte branché en json_script (lu par balance.js).
    assert 'id="account-chart-data"' in html
    assert 'data-chart="balance"' in html
    # Panneau Détails éditable + conteneur détail tx inline (source=patrimoine).
    assert "Détails du compte" in html
    assert 'id="ac-tx-detail"' in html
    assert "source=patrimoine" in html


@pytest.mark.django_db
def test_account_detail_type_is_read_only(client_logged, chf_account, checking_details):
    """Le type de compte est affiché mais N'A PAS de form/édition (hors scope #82)."""
    resp = client_logged.get(
        reverse("patrimoine:account_detail", args=[chf_account.pk])
    )
    html = resp.content.decode()

    assert "Type de compte" in html
    assert chf_account.get_account_type_display() in html
    # Il y a bien des champs éditables (le crayon IBAN pointe vers account_field_form)…
    assert (
        reverse("patrimoine:account_field_form", args=[chf_account.pk, "iban"]) in html
    )
    # …mais AUCUN endpoint d'édition pour le type de compte (lecture seule).
    assert (
        reverse("patrimoine:account_field_form", args=[chf_account.pk, "account_type"])
        not in html
    )


# ── IDOR (SR-001) ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_account_detail_idor_returns_404(client, other_user, chf_account):
    """Compte d'un autre utilisateur → 404 (jamais une fuite), pas 200 ni 403."""
    client.force_login(other_user)
    resp = client.get(reverse("patrimoine:account_detail", args=[chf_account.pk]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_account_subroutes_idor_returns_404(client, other_user, chf_account):
    """Toutes les sous-routes sont scopées for_user → 404 pour un intrus."""
    client.force_login(other_user)
    urls = [
        reverse("patrimoine:set_account_period", args=[chf_account.pk, "1m"]),
        reverse("patrimoine:account_field_form", args=[chf_account.pk, "iban"]),
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "iban"]),
        reverse("patrimoine:account_transactions", args=[chf_account.pk]),
    ]
    # GET pour les GET-routes, POST pour les POST-routes.
    assert client.post(urls[0], {}).status_code == 404
    assert client.get(urls[1]).status_code == 404
    assert client.post(urls[2], {"value": "CH5604835012345678009"}).status_code == 404
    assert client.get(urls[3]).status_code == 404


# ── Période (session, PRG) ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_set_account_period_persists_and_swaps_body(
    client_logged, chf_account, checking_details
):
    """POST période (HTMX) → session mise à jour + corps re-rendu (#account-detail-body)."""
    resp = client_logged.post(
        reverse("patrimoine:set_account_period", args=[chf_account.pk, "1a"]),
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert 'id="account-detail-body"' in resp.content.decode()
    assert client_logged.session[f"patrimoine_account_period_{chf_account.pk}"] == "1a"


@pytest.mark.django_db
def test_set_account_period_invalid_ignored(
    client_logged, chf_account, checking_details
):
    """Période forgée → ignorée (pas d'écriture session), redirect non-HTMX."""
    resp = client_logged.post(
        reverse("patrimoine:set_account_period", args=[chf_account.pk, "999x"])
    )
    assert resp.status_code == 302
    assert f"patrimoine_account_period_{chf_account.pk}" not in client_logged.session


# ── Édition inline IBAN ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_field_form_iban_returns_edit_input(
    client_logged, chf_account, checking_details
):
    """GET form IBAN → input en mode édition ciblant #field-iban."""
    resp = client_logged.get(
        reverse("patrimoine:account_field_form", args=[chf_account.pk, "iban"])
    )
    html = resp.content.decode()
    assert resp.status_code == 200
    assert 'name="value"' in html
    assert 'id="field-iban"' in html
    assert "Enregistrer" in html


@pytest.mark.django_db
def test_field_save_iban_valid_writes_account_only(
    client_logged, chf_account, checking_details
):
    """POST IBAN valide → normalisé + posé sur Account.iban SEUL (mono-écriture #82) ; ligne lecture."""
    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "iban"]),
        {"value": "ch93 0076 2011 6238 5295 7"},
    )
    html = resp.content.decode()

    assert resp.status_code == 200
    chf_account.refresh_from_db()
    expected = "CH9300762011623852957"
    assert chf_account.iban == expected  # Account.iban = source unique
    # Ligne re-rendue en LECTURE (crayon présent, plus de bouton Enregistrer).
    assert "Enregistrer" not in html
    assert expected in html


@pytest.mark.django_db
def test_field_save_iban_invalid_returns_422_and_keeps_db(
    client_logged, chf_account, checking_details
):
    """POST IBAN invalide → 422, message d'erreur, DB inchangée, valeur saisie réaffichée."""
    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "iban"]),
        {"value": "PAS-UN-IBAN"},
    )
    html = resp.content.decode()

    assert resp.status_code == 422
    assert "IBAN invalide" in html
    chf_account.refresh_from_db()
    assert chf_account.iban == "CH5604835012345678009"  # inchangé


@pytest.mark.django_db
def test_field_save_iban_duplicate_returns_422(
    client_logged, chf_account, checking_details, chf_institution, user
):
    """IBAN déjà pris par un autre compte → 422 (unique=True sur Account.iban)."""
    other = Account.objects.create(
        institution=chf_institution,
        name="Autre",
        account_type="checking",
        currency="CHF",
        iban="CH9300762011623852957",
    )
    other.members.add(user)
    CheckingAccount.objects.create(account=other)

    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "iban"]),
        {"value": "CH93 0076 2011 6238 5295 7"},  # collision
    )
    assert resp.status_code == 422
    assert "existe déjà" in resp.content.decode()
    chf_account.refresh_from_db()
    assert chf_account.iban == "CH5604835012345678009"  # inchangé


@pytest.mark.django_db
def test_field_save_iban_clear_rejected_when_no_other_identifier(
    client_logged, chf_account, checking_details
):
    """Vider l'IBAN d'un compte SANS n° de contrat → 422 : sinon plus aucun import
    ne peut le rattacher (invariant d'identité, parité avec le formulaire panel)."""
    assert not chf_account.contract_number  # la fixture n'a pas de n° de contrat
    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "iban"]),
        {"value": ""},
    )
    assert resp.status_code == 422
    assert "n° de contrat" in resp.content.decode()
    chf_account.refresh_from_db()
    assert chf_account.iban == "CH5604835012345678009"  # inchangé


@pytest.mark.django_db
def test_field_save_iban_clear_allowed_when_contract_present(
    client_logged, chf_account, checking_details
):
    """Vider l'IBAN → None est autorisé tant qu'un n° de contrat subsiste (NULL !=
    NULL autorise plusieurs comptes sans IBAN)."""
    chf_account.contract_number = "C-123"
    chf_account.save(update_fields=["contract_number"])
    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "iban"]),
        {"value": ""},
    )
    assert resp.status_code == 200
    chf_account.refresh_from_db()
    assert chf_account.iban is None


# ── Édition inline IBAN — compte d'épargne (#292) ───────────────────────────────


@pytest.mark.django_db
def test_field_form_savings_iban_renders_editable(client_logged, savings_account):
    """RED : l'IBAN n'était pas éditable inline pour un savings (404). Le crayon IBAN
    ouvre désormais le formulaire d'édition (parité avec checking)."""
    resp = client_logged.get(
        reverse("patrimoine:account_field_form", args=[savings_account.pk, "iban"])
    )
    assert resp.status_code == 200
    assert 'id="field-iban"' in resp.content.decode()


@pytest.mark.django_db
def test_field_save_savings_iban_sets_account_iban(client_logged, savings_account):
    """POST IBAN (saisi avec espaces) sur un savings → normalisé + posé sur Account.iban."""
    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[savings_account.pk, "iban"]),
        {"value": "ch56 0483 5012 3456 7800 9"},
    )
    assert resp.status_code == 200
    savings_account.refresh_from_db()
    assert savings_account.iban == "CH5604835012345678009"


# ── Édition inline BIC ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_field_save_bic_valid(client_logged, chf_account, checking_details):
    """POST BIC valide → normalisé (maj), persisté sur CheckingAccount."""
    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "bic"]),
        {"value": "bcvlch2lxxx"},
    )
    assert resp.status_code == 200
    assert CheckingAccount.objects.get(account=chf_account).bic == "BCVLCH2LXXX"


@pytest.mark.django_db
def test_field_save_bic_invalid_returns_422(
    client_logged, chf_account, checking_details
):
    """POST BIC invalide (longueur) → 422, DB inchangée."""
    resp = client_logged.post(
        reverse("patrimoine:account_field_save", args=[chf_account.pk, "bic"]),
        {"value": "XYZ"},
    )
    assert resp.status_code == 422
    assert "BIC invalide" in resp.content.decode()
    assert CheckingAccount.objects.get(account=chf_account).bic == "YUHHCHZZ"


# ── Édition inline Taux (SavingsAccount) ────────────────────────────────────────


@pytest.mark.django_db
def test_field_save_rate_valid(client_logged, savings_account):
    """POST taux valide ('2,75' → Decimal) → persisté sur SavingsAccount."""
    from decimal import Decimal

    resp = client_logged.post(
        reverse(
            "patrimoine:account_field_save", args=[savings_account.pk, "interest_rate"]
        ),
        {"value": "2,75"},
    )
    assert resp.status_code == 200
    assert SavingsAccount.objects.get(account=savings_account).interest_rate == Decimal(
        "2.75"
    )


@pytest.mark.django_db
def test_field_save_rate_invalid_returns_422(client_logged, savings_account):
    """POST taux non numérique → 422, DB inchangée."""
    from decimal import Decimal

    resp = client_logged.post(
        reverse(
            "patrimoine:account_field_save", args=[savings_account.pk, "interest_rate"]
        ),
        {"value": "beaucoup"},
    )
    assert resp.status_code == 422
    assert "Taux invalide" in resp.content.decode()
    assert SavingsAccount.objects.get(account=savings_account).interest_rate == Decimal(
        "1.50"
    )


@pytest.mark.django_db
def test_savings_page_offers_iban_and_rate_not_bic(client_logged, savings_account):
    """Page d'un livret : champs IBAN + Taux éditables (l'IBAN rattache les imports
    UBS, universel checking + savings), mais PAS de BIC (spécifique compte courant)."""
    resp = client_logged.get(
        reverse("patrimoine:account_detail", args=[savings_account.pk])
    )
    html = resp.content.decode()
    # L'apostrophe est échappée par l'autoescape Django (&#x27;).
    assert "intérêt" in html
    assert (
        reverse(
            "patrimoine:account_field_form", args=[savings_account.pk, "interest_rate"]
        )
        in html
    )
    assert (
        reverse("patrimoine:account_field_form", args=[savings_account.pk, "iban"])
        in html
    )
    assert (
        reverse("patrimoine:account_field_form", args=[savings_account.pk, "bic"])
        not in html
    )


# ── Scroll infini transactions ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_account_transactions_scroll_page_2(client_logged, chf_account, make_tx):
    """> 50 tx → page 1 a un sentinel ; page 2 renvoie les lignes restantes."""
    # 60 transactions → 2 pages (TX_PAGE_SIZE=50).
    for i in range(60):
        make_tx(chf_account, "2026-06-08", amount=-(i + 1))

    page1 = client_logged.get(
        reverse("patrimoine:account_detail", args=[chf_account.pk])
    ).content.decode()
    # Sentinel de chargement page 2 présent sur la page 1.
    assert "?page=2" in page1

    page2 = client_logged.get(
        reverse("patrimoine:account_transactions", args=[chf_account.pk]) + "?page=2"
    )
    assert page2.status_code == 200
    assert "tx-" in page2.content.decode()  # des lignes, pas une page vide


# ── Garde champ non éditable ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_field_form_non_editable_field_returns_404(
    client_logged, chf_account, checking_details
):
    """Champ inconnu / non éditable pour ce type (URL forgée) → 404."""
    # interest_rate n'est pas éditable sur un compte CHECKING.
    resp = client_logged.get(
        reverse("patrimoine:account_field_form", args=[chf_account.pk, "interest_rate"])
    )
    assert resp.status_code == 404
    # POST aussi refusé.
    resp = client_logged.post(
        reverse(
            "patrimoine:account_field_save", args=[chf_account.pk, "interest_rate"]
        ),
        {"value": "3"},
    )
    assert resp.status_code == 404
