"""
tests/patrimoine/test_account_wizard.py — wizard #73 (step 2 + création).

Vérifie : auth + garde HX (pas de partial nu) · formulaire avec institution
préremplie et type par défaut selon la catégorie · verrou CHF pour la
prévoyance (le select disabled ne POste pas → le serveur force) · POST succès
= 204 + HX-Redirect bilan · erreurs re-rendues dans le partial, rien en DB.
La logique de création elle-même est testée dans
tests/accounts/test_create_account_service.py — ici on teste la COUCHE HTTP.
"""

import re
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Account, CheckingAccount, Institution, SavingsAccount

# Endpoint HTMX (panel droit) : sans ce header, redirect — cf. picker.
_HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def bank(db):
    # Pas de domain → le post_save logo ne tente aucun fetch.
    return Institution.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF", category="bank"
    )


@pytest.fixture
def exchange(db):
    return Institution.objects.create(
        name="Binance",
        slug="binance",
        country="MT",
        default_currency="USD",
        category="crypto",
    )


def _form_url() -> str:
    return reverse("patrimoine:account_form")


def _create_url() -> str:
    return reverse("patrimoine:account_create")


# =============================================================================
# GET account_form — step 2
# =============================================================================


@pytest.mark.django_db
def test_form_requires_login(client, bank):
    resp = client.get(_form_url(), {"institution": "yuh"}, **_HX)
    assert resp.status_code == 302
    assert "/login" in resp.url or "/connexion" in resp.url


@pytest.mark.django_db
def test_form_direct_nav_redirects(client_logged, bank):
    resp = client_logged.get(_form_url(), {"institution": "yuh"})
    assert resp.status_code == 302
    assert resp.url == reverse("patrimoine:overview")


@pytest.mark.django_db
def test_form_unknown_institution_404(client_logged, bank):
    resp = client_logged.get(_form_url(), {"institution": "nope"}, **_HX)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_form_renders_institution_and_default_type(client_logged, bank):
    resp = client_logged.get(_form_url(), {"institution": "yuh"}, **_HX)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Yuh" in html
    assert 'id="form-dynamic"' in html
    # Catégorie bank → type présélectionné = compte courant.
    # (regex : djLint éclate les attributs des <option> sur plusieurs lignes)
    assert re.search(r'<option value="checking"\s+selected', html)
    # card est exclu du wizard (future issue dédiée).
    assert 'value="card"' not in html


@pytest.mark.django_db
def test_form_crypto_type_is_soon(client_logged, exchange):
    """Crypto exchange = SOON (clé API → sécurité à part) : option visible mais
    désactivée, repli sur brokerage, bandeau SOON pour les exchanges."""
    resp = client_logged.get(_form_url(), {"institution": "binance"}, **_HX)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert re.search(r'<option value="crypto"\s+disabled', html)
    assert re.search(r'<option value="brokerage"\s+selected', html)
    assert "clé API" in html


@pytest.mark.django_db
def test_form_pension_locks_currency_to_chf(client_logged, bank):
    resp = client_logged.get(
        _form_url(), {"institution": "yuh", "account_type": "pension_3a"}, **_HX
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    # Pas de select devise (affichage seul) — le serveur force CHF au POST.
    assert 'name="currency"' not in html
    assert "CHF uniquement" in html
    # Les champs pension sont rendus (plafond annuel).
    assert 'name="annual_limit_chf"' in html


@pytest.mark.django_db
def test_form_checking_renders_iban_field(client_logged, bank):
    resp = client_logged.get(
        _form_url(), {"institution": "yuh", "account_type": "checking"}, **_HX
    )
    assert 'name="iban"' in resp.content.decode()


@pytest.mark.django_db
def test_form_savings_renders_iban_field(client_logged, bank):
    # L'IBAN (UBS épargne…) doit pouvoir se saisir aussi à la CRÉATION d'un
    # savings, pas seulement checking — même flow « Compléter mon patrimoine ».
    resp = client_logged.get(
        _form_url(), {"institution": "yuh", "account_type": "savings"}, **_HX
    )
    assert 'name="iban"' in resp.content.decode()


@pytest.mark.django_db
def test_form_contract_number_rendered_for_all_types(client_logged, bank):
    """Identité d'import : le n° de contrat est proposé quel que soit le type."""
    for account_type in ("checking", "savings", "insurance", "pension_3a"):
        resp = client_logged.get(
            _form_url(), {"institution": "yuh", "account_type": account_type}, **_HX
        )
        assert 'name="contract_number"' in resp.content.decode(), account_type


# =============================================================================
# POST account_create
# =============================================================================


def _checking_payload(**overrides):
    payload = {
        "institution": "yuh",
        "account_type": "checking",
        "name": "Compte courant",
        "currency": "CHF",
        "iban": "CH56 0483 5012 3456 7800 9",
        "bic": "yuhhchzz",
        "contract_number": "  1234567890  ",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_create_requires_login(client, bank):
    resp = client.post(_create_url(), _checking_payload(), **_HX)
    assert resp.status_code == 302
    assert "/login" in resp.url or "/connexion" in resp.url


@pytest.mark.django_db
def test_create_checking_success(client_logged, user, bank):
    resp = client_logged.post(_create_url(), _checking_payload(), **_HX)

    assert resp.status_code == 204
    account = Account.objects.for_user(user).get()
    # #82 PR C : succès → page zoom du compte créé (plus le bilan).
    assert resp["HX-Redirect"] == reverse(
        "patrimoine:account_detail", args=[account.pk]
    )
    # IBAN normalisé (espaces retirés, majuscules) — posé sur Account.iban SEUL (#82).
    assert account.iban == "CH5604835012345678009"
    # Identité d'import bis : n° de contrat commun à tous les types (trimé).
    assert account.contract_number == "1234567890"
    details = CheckingAccount.objects.get(account=account)
    assert details.bic == "YUHHCHZZ"


@pytest.mark.django_db
def test_create_savings_with_iban(client_logged, user, bank):
    # Bug réel (épargne UBS) : à la création d'un savings, l'IBAN saisi doit
    # être posé sur Account.iban (clé de rattachement des imports), normalisé.
    resp = client_logged.post(
        _create_url(),
        {
            "institution": "yuh",
            "account_type": "savings",
            "name": "Épargne UBS",
            "currency": "CHF",
            "iban": "ch56 0483 5012 3456 7800 9",
            "interest_rate": "1.5",
            "contract_number": "",
        },
        **_HX,
    )

    assert resp.status_code == 204
    account = Account.objects.for_user(user).get()
    assert account.account_type == "savings"
    assert account.iban == "CH5604835012345678009"  # normalisé (sans espaces, maj)
    assert account.savings_account.interest_rate == Decimal("1.5")


@pytest.mark.django_db
def test_create_pension_forces_chf(client_logged, user, bank):
    """Le select devise disabled ne POste rien → le serveur force CHF (jamais confiance au client)."""
    resp = client_logged.post(
        _create_url(),
        {
            "institution": "yuh",
            "account_type": "pension_3a",
            "name": "3e pilier",
            "currency": "EUR",  # forgé — doit être ignoré
            "contract_number": "3A-TEST",
            "annual_limit_chf": "7056",
        },
        **_HX,
    )

    assert resp.status_code == 204
    account = Account.objects.for_user(user).get()
    assert account.currency == "CHF"


@pytest.mark.django_db
def test_create_savings_accepts_comma_decimal(client_logged, user, bank):
    resp = client_logged.post(
        _create_url(),
        {
            "institution": "yuh",
            "account_type": "savings",
            "name": "Livret",
            "currency": "EUR",
            "contract_number": "LIV-TEST",
            "interest_rate": "3,5",
        },
        **_HX,
    )

    assert resp.status_code == 204
    account = Account.objects.for_user(user).get()
    assert SavingsAccount.objects.get(account=account).interest_rate == Decimal("3.5")


@pytest.mark.django_db
def test_create_crypto_type_rejected(client_logged, exchange):
    """Le disabled du select se forge — le POST refuse les types SOON."""
    resp = client_logged.post(
        _create_url(),
        {
            "institution": "binance",
            "account_type": "crypto",
            "name": "Binance Spot",
            "currency": "USD",
        },
        **_HX,
    )

    assert resp.status_code == 422
    assert "invalide" in resp.content.decode()
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_create_invalid_type_rerenders_with_error(client_logged, bank):
    resp = client_logged.post(
        _create_url(), _checking_payload(account_type="yolo"), **_HX
    )

    assert resp.status_code == 422
    assert "Type de compte invalide" in resp.content.decode()
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_create_missing_name_rerenders_with_error(client_logged, bank):
    resp = client_logged.post(_create_url(), _checking_payload(name="  "), **_HX)

    assert resp.status_code == 422
    assert "obligatoire" in resp.content.decode()
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_create_bad_decimal_rerenders_with_error(client_logged, bank):
    resp = client_logged.post(
        _create_url(),
        {
            "institution": "yuh",
            "account_type": "savings",
            "name": "Livret",
            "currency": "EUR",
            "interest_rate": "abc",
        },
        **_HX,
    )

    assert resp.status_code == 422
    assert "invalide" in resp.content.decode()
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_create_duplicate_iban_rerenders_with_error(client_logged, bank):
    first = client_logged.post(_create_url(), _checking_payload(), **_HX)
    assert first.status_code == 204

    resp = client_logged.post(_create_url(), _checking_payload(name="Doublon"), **_HX)

    assert resp.status_code == 422
    # Le formulaire est re-rendu avec un message (unicité IBAN via full_clean).
    assert "existe déjà" in resp.content.decode()
    assert Account.objects.count() == 1


@pytest.mark.django_db
def test_create_missing_identifier_rerenders_with_error(client_logged, bank):
    """Ni IBAN ni n° de contrat → refus avec message (identité d'import requise)."""
    resp = client_logged.post(
        _create_url(),
        {
            "institution": "yuh",
            "account_type": "savings",
            "name": "Livret orphelin",
            "currency": "CHF",
        },
        **_HX,
    )

    assert resp.status_code == 422
    assert "n° de contrat" in resp.content.decode()
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_create_direct_post_redirects(client_logged, bank):
    """Symétrie de la garde HX : un POST hors HTMX redirige, ne crée rien."""
    resp = client_logged.post(_create_url(), _checking_payload())  # sans header HX

    assert resp.status_code == 302
    assert resp.url == reverse("patrimoine:overview")
    assert Account.objects.count() == 0
