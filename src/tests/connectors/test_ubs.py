"""
tests/connectors/test_ubs.py — Tests unitaires de UBSConnector.

Tests PURS PYTHON — aucun accès à la base de données.

Fixture CSV (ubs_sample.csv) — structure :
    9 lignes metadata (dont 1 vide) + header + 3 transactions

    TX001 : carte avec heure 12:36:26 → time="12:36:26", débit -75.00 CHF
    TX002 : virement e-banking sans heure → time=None, débit -5500.00 CHF
    TX003 : virement entrant sans heure → time=None, crédit +7349.70 CHF

    Metadata :
        Ligne 2 : IBAN:;CH00 0000 0000 0000 0000 0;
        Ligne 6 : Solde final:;12000.00;
"""

from connectors.ubs.parser import UBSConnector

# =============================================================================
# parse() — comportement général
# =============================================================================


def test_parse_returns_correct_transaction_count(ubs_csv_path):
    """3 transactions dans le fichier UBS de test."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    assert len(transactions) == 3


def test_parse_debit_amount_is_negative(ubs_csv_path):
    """TX001 est un paiement carte → montant négatif."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    assert transactions[0]["amount"] == -75.00


def test_parse_credit_amount_is_positive(ubs_csv_path):
    """TX003 est un virement entrant → montant positif."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    assert transactions[2]["amount"] == 7349.70


def test_parse_currency_is_chf(ubs_csv_path):
    """Toutes les transactions du fixture sont en CHF."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    for tx in transactions:
        assert tx["currency"] == "CHF"


# =============================================================================
# parse() — champ time (présent pour les cartes, None pour les virements)
# =============================================================================


def test_parse_time_present_for_card_transaction(ubs_csv_path):
    """
    TX001 est un paiement carte : l'heure est dans la colonne 'Heure de transaction'.
    UBS est le seul connecteur à fournir l'heure.
    """
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    assert transactions[0]["time"] == "12:36:26"


def test_parse_time_is_none_for_bank_transfer(ubs_csv_path):
    """TX002 est un virement e-banking : pas d'heure dans UBS exports."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    assert transactions[1]["time"] is None


def test_parse_time_is_none_for_incoming_transfer(ubs_csv_path):
    """TX003 est un virement entrant : pas d'heure."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    assert transactions[2]["time"] is None


# =============================================================================
# parse() — description et merchant
# =============================================================================


def test_parse_description_raw_combines_descriptions(ubs_csv_path):
    """
    description_raw = Description1 | Description2 | Description3 (parties non-vides).
    Ce format préserve toute l'information bancaire pour l'audit et les règles.
    """
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    # TX001 : "FEEL EAT SARL LAUSANNE | Paiement carte de debit | No de transaction TX001"
    assert "FEEL EAT SARL LAUSANNE" in transactions[0]["description_raw"]
    assert "Paiement carte de debit" in transactions[0]["description_raw"]


def test_parse_merchant_name_is_normalized(ubs_csv_path):
    """merchant_name = Description1 avec espaces multiples réduits + uppercase."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    # "FEEL EAT SARL            LAUSANNE" → "FEEL EAT SARL LAUSANNE"
    assert transactions[0]["merchant_name"] == "FEEL EAT SARL LAUSANNE"


# =============================================================================
# parse() — import_hash
# =============================================================================


def test_parse_import_hashes_are_unique(ubs_csv_path):
    """Chaque transaction a un hash distinct."""
    connector = UBSConnector()
    transactions = connector.parse(ubs_csv_path)
    hashes = [tx["import_hash"] for tx in transactions]
    assert len(hashes) == len(set(hashes))


# =============================================================================
# extract_balance() — ligne 6 du bloc metadata
# =============================================================================


def test_extract_balance_from_metadata(ubs_csv_path):
    """Solde final lu depuis la ligne 6 du fichier UBS."""
    connector = UBSConnector()
    assert connector.extract_balance(ubs_csv_path) == 12000.00


# =============================================================================
# extract_account_identifier() — IBAN depuis ligne 2
# =============================================================================


def test_extract_account_identifier_returns_normalized_iban(ubs_csv_path):
    """
    IBAN extrait de la ligne 2 et normalisé (espaces supprimés).

    Pourquoi normaliser ?
    - Le fichier UBS écrit "CH00 0000 0000 0000 0000 0" (avec espaces pour lisibilité)
    - Account.contract_number stocke l'IBAN sans espaces
    - La comparaison doit être exacte → on normalise côté connecteur
    """
    connector = UBSConnector()
    iban = connector.extract_account_identifier(ubs_csv_path)
    # Fixture IBAN "CH00 0000 0000 0000 0000 0" → sans espaces
    assert iban == "CH0000000000000000000"
    assert " " not in iban


# =============================================================================
# matches_file() — détection du format
# =============================================================================


def test_matches_file_true_for_ubs_csv(ubs_csv_path):
    """Le fichier fixture UBS est reconnu comme format UBS."""
    assert UBSConnector.matches_file(ubs_csv_path) is True


def test_matches_file_false_for_yuh_csv(yuh_csv_path):
    """Un fichier Yuh ne doit PAS être reconnu comme UBS."""
    assert UBSConnector.matches_file(yuh_csv_path) is False
