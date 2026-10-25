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
    """PAYMENT_TRANSACTION_OUT → merchant_name depuis RECIPIENT, uppercase."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    # Ligne 4 : RECIPIENT = """LANDLORD SA"""
    assert transactions[2]["merchant_name"] == "LANDLORD SA"


def test_parse_merchant_name_from_sender_for_payment_in(yuh_csv_path):
    """PAYMENT_TRANSACTION_IN → merchant_name depuis SENDER, uppercase."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_csv_path)
    # Ligne 3 : SENDER = """EMPLOYER SA"""
    assert transactions[1]["merchant_name"] == "EMPLOYER SA"


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
# extract_balance() — Yuh n'expose aucun solde (voir docstring module)
# =============================================================================


def test_extract_balance_always_returns_none():
    """
    Yuh n'expose de solde ni dans le fichier ni dans le nom de fichier.

    Le nombre après " - " dans le nom ("Activités_2026_09_18 - 46,933.CSV")
    ressemble à un solde mais n'en est pas un : vérifié faux sur un compte
    réel (~30k CHF d'écart avec le total confirmé par les transactions).
    extract_balance() ne doit plus jamais le lire, quelle que soit la forme
    du nom de fichier (droit, encodé URL, suffixe doublon navigateur...).
    """
    connector = YuhConnector()
    names = [
        "Activités_2026_03_17 - 33,344.CSV",
        "export_yuh.csv",
        "Activit%C3%A9s_2026_04_29%20-%2036,341.CSV",
        "Activités_2026_09_11 - 46,461 2.CSV",
        "Activit%C3%A9s_2026_09_11%20-%2046,461 2.CSV",
        "yuh_sample_2026_03_17.csv",
    ]
    for name in names:
        assert connector.extract_balance(Path(name)) is None


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


# =============================================================================
# parse() — conversions de devise (DEBIT + CREDIT sur la même ligne)
#
# Bug corrigé : une ligne BANK_AUTO_ORDER_EXECUTED / BANK_ORDER_EXECUTED avec
# DEBIT ET CREDIT remplis (2 devises différentes) ne produisait QU'UNE
# TransactionDict (la jambe DEBIT) — la jambe CREDIT disparaissait en
# silence. Fixture : yuh_fx_sample.csv (6 lignes, voir conftest.py).
# =============================================================================


def test_fx_conversion_row_produces_two_legs(yuh_fx_csv_path):
    """DEBIT -8.30 CHF + CREDIT 8.90 EUR sur 1 ligne → 2 TransactionDict, pas 1."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_fx_csv_path)
    eur_conversion = [
        t
        for t in transactions
        if t["description_raw"] == "Change automatique Francs suisses"
        and t["currency"] in ("CHF", "EUR")
        and abs(t["amount"]) in (8.30, 8.90)
    ]
    assert len(eur_conversion) == 2
    chf_leg = next(t for t in eur_conversion if t["currency"] == "CHF")
    eur_leg = next(t for t in eur_conversion if t["currency"] == "EUR")
    assert chf_leg["amount"] == -8.30
    assert eur_leg["amount"] == 8.90


def test_fx_conversion_anticipates_gbp_and_usd(yuh_fx_csv_path):
    """
    Anticipe les devises au-delà de EUR : GBP et USD produisent la même
    scission 2-jambes — pas un traitement EUR-only accidentel.
    """
    connector = YuhConnector()
    transactions = connector.parse(yuh_fx_csv_path)
    currencies_seen = {t["currency"] for t in transactions}
    assert {"CHF", "EUR", "GBP", "USD"} <= currencies_seen

    gbp_leg = next(t for t in transactions if t["currency"] == "GBP")
    assert gbp_leg["amount"] == 167.49
    usd_leg = next(t for t in transactions if t["currency"] == "USD")
    assert usd_leg["amount"] == 14.99


def test_fx_legs_share_paired_leg_key(yuh_fx_csv_path):
    """Les 2 jambes d'UNE conversion partagent la même paired_leg_key."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_fx_csv_path)
    gbp_row_legs = [
        t
        for t in transactions
        if t["description_raw"] == "Change automatique Francs suisses"
        and abs(t["amount"]) in (179.94, 167.49)
    ]
    assert len(gbp_row_legs) == 2
    assert gbp_row_legs[0]["paired_leg_key"] is not None
    assert gbp_row_legs[0]["paired_leg_key"] == gbp_row_legs[1]["paired_leg_key"]


def test_fx_legs_have_distinct_import_hashes(yuh_fx_csv_path):
    """Même paired_leg_key mais import_hash différent — sinon bulk_create plante (unique=True)."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_fx_csv_path)
    hashes = [t["import_hash"] for t in transactions]
    assert len(hashes) == len(set(hashes))


def test_non_conversion_rows_have_no_paired_leg_key(yuh_fx_csv_path):
    """Une ligne normale (carte, virement) → paired_leg_key=None, pas de scission."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_fx_csv_path)
    card_tx = next(t for t in transactions if t["description_raw"] == "TEST MERCHANT")
    transfer_tx = next(
        t for t in transactions if t["description_raw"] == "Transfert à TEST PERSON"
    )
    assert card_tx["paired_leg_key"] is None
    assert transfer_tx["paired_leg_key"] is None


def test_single_leg_bank_order_with_negative_credit_not_split(yuh_fx_csv_path):
    """
    BANK_ORDER_EXECUTED avec DEBIT vide et CREDIT négatif (-1872.78 CHF, vente
    de CHF — cas réel observé) : 1 seule jambe, signe conservé tel quel (pas
    de abs()), pas de scission puisque DEBIT est vide.
    """
    connector = YuhConnector()
    transactions = connector.parse(yuh_fx_csv_path)
    sell_chf = [
        t for t in transactions if t["description_raw"] == "Échange Francs suisses"
    ]
    assert len(sell_chf) == 1
    assert sell_chf[0]["amount"] == -1872.78
    assert sell_chf[0]["currency"] == "CHF"
    assert sell_chf[0]["paired_leg_key"] is None


def test_fx_conversion_parse_is_idempotent(yuh_fx_csv_path):
    """Parser le même fichier 2 fois → mêmes import_hash ET mêmes paired_leg_key."""
    connector = YuhConnector()
    first = connector.parse(yuh_fx_csv_path)
    second = connector.parse(yuh_fx_csv_path)
    assert [t["import_hash"] for t in first] == [t["import_hash"] for t in second]
    assert [t["paired_leg_key"] for t in first] == [t["paired_leg_key"] for t in second]


def test_fx_fixture_transaction_count(yuh_fx_csv_path):
    """6 lignes source → 9 TransactionDict (3 lignes scindées en 2 + 3 lignes simples)."""
    connector = YuhConnector()
    transactions = connector.parse(yuh_fx_csv_path)
    assert len(transactions) == 9
