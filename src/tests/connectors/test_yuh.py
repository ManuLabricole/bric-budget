"""
tests/connectors/test_yuh.py — Tests unitaires de YuhConnector.

Ces tests sont PURS PYTHON : aucun accès à la base de données.
Le connecteur ne fait que lire un fichier et retourner des dicts — pas de Django.

Fixture CSV (yuh_sample.csv) — 5 lignes de données :
    Ligne 2 : CARD_TRANSACTION_OUT   -25.40 CHF  card **** 1150
    Ligne 3 : PAYMENT_TRANSACTION_IN +5500.00 CHF  from EMPLOYER SA
    Ligne 4 : PAYMENT_TRANSACTION_OUT -800.00 CHF  to LANDLORD SA
    Ligne 5 : REWARD_RECEIVED         → SKIPPÉ (blacklist)
    Ligne 6 : BANK_ORDER_EXECUTED    +9.22 CHF   (conversion FX)

Résultat attendu : 4 transactions importées, 1 skippée.
"""

from pathlib import Path

from connectors.yuh.parser import YuhConnector

# =============================================================================
# parse() — comportement général
# =============================================================================


def test_parse_returns_correct_transaction_count(yuh_csv_path):
    """4 transactions sur 5 lignes — REWARD_RECEIVED est exclu."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    assert len(transactions) == 4


def test_parse_debit_amount_is_negative(yuh_csv_path):
    """CARD_TRANSACTION_OUT (première ligne) → montant négatif."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    # Ligne 2 = index 0 dans les résultats
    assert transactions[0]["amount"] == -25.40


def test_parse_credit_amount_is_positive(yuh_csv_path):
    """PAYMENT_TRANSACTION_IN (deuxième ligne) → montant positif."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    assert transactions[1]["amount"] == 5500.00


def test_parse_date_converted_to_iso_format(yuh_csv_path):
    """DD/MM/YYYY → YYYY-MM-DD (ISO 8601)."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    # Toutes les dates du fixture sont 17/03/2026, 17/03/2026, 18/03/2026, 19/03/2026
    assert transactions[0]["date"] == "2026-03-17"
    assert transactions[2]["date"] == "2026-03-18"


def test_parse_time_is_always_none(yuh_csv_path):
    """Yuh n'exporte pas l'heure — time=None pour toutes les transactions."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    for tx in transactions:
        assert tx["time"] is None


def test_parse_currency_extracted(yuh_csv_path):
    """La devise est extraite depuis DEBIT CURRENCY ou CREDIT CURRENCY."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    assert transactions[0]["currency"] == "CHF"  # CARD_TRANSACTION_OUT (debit CHF)
    assert transactions[1]["currency"] == "CHF"  # PAYMENT_TRANSACTION_IN (credit CHF)


# =============================================================================
# parse() — carte et merchant
# =============================================================================


def test_parse_card_last_four_extracted(yuh_csv_path):
    """'**** 1150' → card_last_four='1150' pour CARD_TRANSACTION_OUT."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    assert transactions[0]["card_last_four"] == "1150"


def test_parse_card_last_four_none_for_transfer(yuh_csv_path):
    """PAYMENT_TRANSACTION_IN (virement) → pas de numéro de carte."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    assert transactions[1]["card_last_four"] is None


def test_parse_merchant_name_from_recipient_for_payment_out(yuh_csv_path):
    """PAYMENT_TRANSACTION_OUT → merchant_name depuis RECIPIENT, title-cased."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    # Ligne 4 : RECIPIENT = """LANDLORD SA"""
    assert transactions[2]["merchant_name"] == "Landlord Sa"


def test_parse_merchant_name_from_sender_for_payment_in(yuh_csv_path):
    """PAYMENT_TRANSACTION_IN → merchant_name depuis SENDER, title-cased."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    # Ligne 3 : SENDER = """EMPLOYER SA"""
    assert transactions[1]["merchant_name"] == "Employer Sa"


# =============================================================================
# parse() — import_hash déduplication
# =============================================================================


def test_parse_import_hashes_are_unique(yuh_csv_path):
    """Chaque transaction a un hash différent — pas de doublon en masse."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    hashes = [tx["import_hash"] for tx in transactions]
    assert len(hashes) == len(set(hashes))


def test_parse_import_hash_is_deterministic(yuh_csv_path):
    """Parser le même fichier deux fois → mêmes hashes (idempotent)."""
    connector = YuhConnector()
    hashes1 = [tx["import_hash"] for tx in connector.parse(yuh_csv_path)]
    hashes2 = [tx["import_hash"] for tx in connector.parse(yuh_csv_path)]
    assert hashes1 == hashes2


# =============================================================================
# extract_balance() — lecture depuis le nom de fichier
# =============================================================================


def test_extract_balance_parses_filename_pattern():
    """
    Le solde est encodé dans le nom du fichier Yuh :
    "Activités_2026_03_17 - 33,344.CSV" → 33344.0

    extract_balance() lit filepath.name — pas le contenu du fichier.
    On peut donc passer un Path avec un nom fictif sans ouvrir de fichier.
    """
    connector = YuhConnector()
    p = Path("Activités_2026_03_17 - 33,344.CSV")
    assert connector.extract_balance(p) == 33344.0


def test_extract_balance_handles_no_separator():
    """Nom de fichier sans pattern ' - BALANCE' → None."""
    connector = YuhConnector()
    p = Path("export_yuh.csv")
    assert connector.extract_balance(p) is None


def test_extract_balance_single_digit():
    """Solde sans virgule de millier."""
    connector = YuhConnector()
    p = Path("Activités_2026_03_17 - 500.CSV")
    assert connector.extract_balance(p) == 500.0


# =============================================================================
# matches_file() — détection du format
# =============================================================================


def test_matches_file_true_for_yuh_csv(yuh_csv_path):
    """Le fichier fixture Yuh est reconnu comme format Yuh."""
    assert YuhConnector.matches_file(yuh_csv_path) is True


def test_matches_file_false_for_ubs_csv(ubs_csv_path):
    """Un fichier UBS ne doit PAS être reconnu comme Yuh."""
    assert YuhConnector.matches_file(ubs_csv_path) is False


def test_matches_file_false_for_non_csv(tmp_path):
    """Un fichier non-CSV (.xlsx, .txt...) → False sans crash."""
    fake = tmp_path / "export.xlsx"
    fake.write_text("dummy content")
    assert YuhConnector.matches_file(fake) is False
