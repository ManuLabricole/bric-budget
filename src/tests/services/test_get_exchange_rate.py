"""
tests/services/test_get_exchange_rate.py — Tests de get_exchange_rate().

Pourquoi tester cette fonction séparément ?
-------------------------------------------
Elle a été écrite et utilisée pour backfiller 3652 transactions lors de la session
Phase 2A — mais n'avait aucun test. Elle combine :
    - Un accès DB (ExchangeRate cache)
    - Un appel réseau (frankfurter.app)
    - Une conversion Decimal
    - Un stockage en DB

Si l'un de ces éléments régresse (format API changé, erreur Decimal...) on veut
le savoir immédiatement. On mocke l'appel réseau pour rester déterministe.

Comportements testés :
    1. Shortcut same currency     : EUR→EUR → Decimal("1") sans DB ni API
    2. DB cache hit               : taux déjà en DB → retourné, API jamais appelée
    3. API call + stockage DB     : absent de la DB → appel API, résultat stocké en DB
    4. Résultat stocké réutilisé  : 2ème appel après stockage → pas de 2ème appel API
    5. API down → None            : erreur réseau → None, import ne crashe pas
    6. Mauvais format API → None  : réponse sans la clé 'rates' → None
"""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from accounts.models import ExchangeRate
from services.exchange_rates import get_exchange_rate

TEST_DATE = date(2026, 3, 17)


# =============================================================================
# Helper — crée un mock de réponse urllib qui simule frankfurter.app
# =============================================================================


def mock_api_response(to_currency: str, rate: float):
    """
    Simule une réponse HTTP de frankfurter.app.

    On mocke urllib.request.urlopen (context manager) pour éviter tout appel réseau.
    La réponse retourne un JSON {'rates': {to_currency: rate}}.
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"rates": {to_currency: rate}}).encode()
    # urlopen est un context manager (with urllib.request.urlopen(...) as resp)
    mock_resp.__enter__ = lambda self: mock_resp
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# =============================================================================
# 1. Shortcut : from_currency == to_currency → Decimal("1") immédiatement
# =============================================================================


def test_same_currency_returns_one_without_db_or_api():
    """
    CHF→CHF → Decimal("1") — pas de DB, pas d'API.

    Ce shortcut est critique : sans lui, chaque transaction CHF déclencherait
    un appel à frankfurter.app qui échouerait (EUR→EUR n'existe pas dans l'API).
    """
    result = get_exchange_rate(TEST_DATE, "CHF", "CHF")
    assert result == Decimal("1")


def test_same_currency_default_to_chf():
    """get_exchange_rate(date, "CHF") utilise to_currency="CHF" par défaut."""
    result = get_exchange_rate(TEST_DATE, "CHF")
    assert result == Decimal("1")


# =============================================================================
# 2. DB cache hit — le taux existe déjà, pas d'appel API
# =============================================================================


@pytest.mark.django_db
def test_db_cache_hit_returns_existing_rate(db):
    """
    Si ExchangeRate existe pour cette date → retourné directement.

    C'est la stratégie cache : on n'appelle jamais l'API deux fois pour la même date.
    Un import CIC de 200 lignes sur 3 mois ne fait que ~90 appels API max
    (une par date unique), pas 200.
    """
    ExchangeRate.objects.create(
        date=TEST_DATE,
        from_currency="EUR",
        to_currency="CHF",
        rate=Decimal("0.9312"),
    )

    # Si l'API était appelée ici, le test échouerait (pas de mock → vraie connexion)
    # Le fait qu'il passe sans mock prouve que la DB cache est lue en premier
    result = get_exchange_rate(TEST_DATE, "EUR", "CHF")
    assert result == Decimal("0.9312")


@pytest.mark.django_db
def test_db_cache_hit_does_not_call_api(db):
    """API non appelée si le taux est en cache DB."""
    ExchangeRate.objects.create(
        date=TEST_DATE, from_currency="EUR", to_currency="CHF", rate=Decimal("0.93")
    )

    with patch("services.exchange_rates.urllib.request.urlopen") as mock_urlopen:
        get_exchange_rate(TEST_DATE, "EUR", "CHF")
        mock_urlopen.assert_not_called()


# =============================================================================
# 3. API call — taux absent en DB → appel API, stockage, retour
# =============================================================================


@pytest.mark.django_db
def test_api_called_when_rate_not_in_db(db):
    """
    Taux absent → appel API mocké → rate retourné.

    On vérifie que le résultat est bien le taux venu de l'API (0.9321).
    """
    with patch(
        "services.exchange_rates.urllib.request.urlopen",
        return_value=mock_api_response("CHF", 0.9321),
    ):
        result = get_exchange_rate(TEST_DATE, "EUR", "CHF")

    assert result == Decimal("0.9321")


@pytest.mark.django_db
def test_rate_stored_in_db_after_api_call(db):
    """
    Après l'appel API, le taux doit être persisté dans ExchangeRate.

    C'est l'étape 3 de get_exchange_rate() :
    "Stocker en DB pour les prochains imports".
    """
    assert ExchangeRate.objects.count() == 0

    with patch(
        "services.exchange_rates.urllib.request.urlopen",
        return_value=mock_api_response("CHF", 0.9321),
    ):
        get_exchange_rate(TEST_DATE, "EUR", "CHF")

    assert ExchangeRate.objects.count() == 1
    stored = ExchangeRate.objects.first()
    assert stored is not None
    assert stored.from_currency == "EUR"
    assert stored.to_currency == "CHF"
    assert stored.rate == Decimal("0.9321")
    assert stored.date == TEST_DATE


@pytest.mark.django_db
def test_second_call_uses_db_cache_not_api(db):
    """
    2ème appel pour la même date → cache DB, pas de 2ème appel API.

    L'objectif : N transactions le même jour = 1 seul appel API, pas N.
    """
    with patch(
        "services.exchange_rates.urllib.request.urlopen",
        return_value=mock_api_response("CHF", 0.9321),
    ) as mock_urlopen:
        get_exchange_rate(TEST_DATE, "EUR", "CHF")  # appel 1 : API
        get_exchange_rate(TEST_DATE, "EUR", "CHF")  # appel 2 : DB cache

    # urlopen appelé exactement une fois, pas deux
    assert mock_urlopen.call_count == 1


# =============================================================================
# 4. API down → None sans crash
# =============================================================================


@pytest.mark.django_db
def test_api_error_returns_none_without_crash(db):
    """
    Erreur réseau → None. L'import continue, amount_chf reste None.

    Comportement "best effort" : on ne veut pas perdre 200 transactions parce
    que frankfurter.app était down pendant 10 secondes.
    """
    import urllib.error

    with patch(
        "services.exchange_rates.urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        result = get_exchange_rate(TEST_DATE, "EUR", "CHF")

    assert result is None


@pytest.mark.django_db
def test_api_unexpected_json_format_returns_none(db):
    """
    L'API retourne un JSON valide mais sans la clé 'rates' → None sans crash.

    Défensif contre un changement de format de frankfurter.app.
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"error": "not found"}).encode()
    mock_resp.__enter__ = lambda self: mock_resp
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch(
        "services.exchange_rates.urllib.request.urlopen", return_value=mock_resp
    ):
        result = get_exchange_rate(TEST_DATE, "EUR", "CHF")

    assert result is None
