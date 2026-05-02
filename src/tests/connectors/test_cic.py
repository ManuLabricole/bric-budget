"""
tests/connectors/test_cic.py — Tests unitaires de CICConnector.

Tests PURS PYTHON — aucun accès à la base de données.

Fixture CIC (créée par conftest.py avec openpyxl) :
    Feuille "Cpt CC"       : 3 transactions, RIB 10096 18027 00064764601
    Feuille "Cpt LivretA"  : 2 transactions, RIB 10096 18027 00087654321
    Feuille "Vos comptes"  : récap (ignorée par le parser)

Chaque feuille compte a une ligne footer "Solde au..." → skippée.
"""

from connectors.cic.parser import CICConnector

# =============================================================================
# matches_file() — détection du format
# =============================================================================


def test_matches_file_true_for_cic_xlsx(cic_file):
    """Un .xlsx avec une feuille 'Vos comptes' est reconnu comme CIC."""
    assert CICConnector.matches_file(cic_file) is True


def test_matches_file_false_for_csv(yuh_csv_path):
    """Un .csv n'est jamais un fichier CIC (CIC exporte en .xlsx)."""
    assert CICConnector.matches_file(yuh_csv_path) is False


def test_matches_file_false_for_unknown_xlsx(tmp_path):
    """Un .xlsx sans feuille 'Vos comptes' n'est pas un fichier CIC."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    filepath = tmp_path / "unknown.xlsx"
    wb.save(str(filepath))
    assert CICConnector.matches_file(filepath) is False


# =============================================================================
# get_account_sheets() — découverte des feuilles comptes
# =============================================================================


def test_get_account_sheets_returns_two_sheets(cic_file):
    """2 feuilles de compte (CC + LivretA) — 'Vos comptes' ignorée."""
    connector = CICConnector()
    sheets = connector.get_account_sheets(cic_file)
    assert len(sheets) == 2


def test_get_account_sheets_names(cic_file):
    """Les noms des feuilles retournées correspondent aux feuilles de compte."""
    connector = CICConnector()
    sheets = connector.get_account_sheets(cic_file)
    names = [s["sheet_name"] for s in sheets]
    assert "Cpt CC" in names
    assert "Cpt LivretA" in names


def test_get_account_sheets_rib_extracted(cic_file):
    """Le RIB est extrait et normalisé (sans espaces) pour chaque feuille."""
    connector = CICConnector()
    sheets = connector.get_account_sheets(cic_file)
    cc_sheet = next(s for s in sheets if s["sheet_name"] == "Cpt CC")
    # "10096 18027 00064764601" → "100961802700064764601"
    assert cc_sheet["rib"] == "100961802700064764601"
    assert " " not in cc_sheet["rib"]


def test_get_account_sheets_account_type_hint_checking(cic_file):
    """Titre avec 'C/C' → account_type_hint = 'checking'."""
    connector = CICConnector()
    sheets = connector.get_account_sheets(cic_file)
    cc_sheet = next(s for s in sheets if s["sheet_name"] == "Cpt CC")
    assert cc_sheet["account_type_hint"] == "checking"


def test_get_account_sheets_account_type_hint_savings(cic_file):
    """Titre avec 'LIVRET' → account_type_hint = 'savings'."""
    connector = CICConnector()
    sheets = connector.get_account_sheets(cic_file)
    la_sheet = next(s for s in sheets if s["sheet_name"] == "Cpt LivretA")
    assert la_sheet["account_type_hint"] == "savings"


def test_get_account_sheets_balance_extracted(cic_file):
    """Le solde final est extrait depuis la ligne footer de chaque feuille."""
    connector = CICConnector()
    sheets = connector.get_account_sheets(cic_file)
    cc_sheet = next(s for s in sheets if s["sheet_name"] == "Cpt CC")
    assert cc_sheet["balance"] == 798.27


# =============================================================================
# parse_sheet() — parsing d'une feuille
# =============================================================================


def test_parse_sheet_cc_returns_correct_count(cic_file):
    """La feuille C/C contient 3 transactions (la ligne footer est skippée)."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    assert len(transactions) == 3


def test_parse_sheet_la_returns_correct_count(cic_file):
    """La feuille Livret A contient 2 transactions."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt LivretA")
    assert len(transactions) == 2


def test_parse_sheet_debit_is_negative(cic_file):
    """Paiement carte (row 6 de CC) → montant négatif."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    # Row 6 : débit -25.40
    assert transactions[0]["amount"] == -25.40


def test_parse_sheet_credit_is_positive(cic_file):
    """Virement entrant (row 7 de CC) → montant positif."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    # Row 7 : crédit +2500.00
    assert transactions[1]["amount"] == 2500.00


def test_parse_sheet_currency_is_eur(cic_file):
    """Toutes les transactions CIC du fixture sont en EUR."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    for tx in transactions:
        assert tx["currency"] == "EUR"


def test_parse_sheet_date_is_iso_format(cic_file):
    """openpyxl retourne datetime → le parser convertit en 'YYYY-MM-DD'."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    assert transactions[0]["date"] == "2026-03-17"


def test_parse_sheet_time_is_none(cic_file):
    """CIC n'exporte pas l'heure — time=None pour toutes les transactions."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    for tx in transactions:
        assert tx["time"] is None


def test_parse_sheet_card_last_four_extracted(cic_file):
    """'PAIEMENT PSC 1703 LAUSANNE MIGROS CARTE 8703' → card_last_four='8703'."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    # Row 6 : paiement carte
    assert transactions[0]["card_last_four"] == "8703"


def test_parse_sheet_card_none_for_transfer(cic_file):
    """'VIR SEPA EMPLOYER SA' → pas de numéro carte."""
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    # Row 7 : virement sans CARTE dans la description
    assert transactions[1]["card_last_four"] is None


def test_parse_sheet_merchant_cleaned(cic_file):
    """
    'PAIEMENT PSC 1703 LAUSANNE MIGROS CARTE 8703'
    → préfixe 'PAIEMENT PSC 1703 ' supprimé, suffixe 'CARTE 8703' supprimé
    → title-cased.
    """
    connector = CICConnector()
    transactions = connector.parse_sheet(cic_file, "Cpt CC")
    # "LAUSANNE MIGROS" → "Lausanne Migros"
    assert transactions[0]["merchant_name"] == "Lausanne Migros"


def test_parse_sheet_import_hashes_are_unique(cic_file):
    """Chaque transaction a un hash distinct — même si montant et date identiques."""
    connector = CICConnector()
    txs_cc = connector.parse_sheet(cic_file, "Cpt CC")
    txs_la = connector.parse_sheet(cic_file, "Cpt LivretA")
    all_hashes = [tx["import_hash"] for tx in txs_cc + txs_la]
    assert len(all_hashes) == len(set(all_hashes))


# =============================================================================
# parse() — méthode agrégée (héritée de BaseConnector)
# =============================================================================


def test_parse_combines_all_sheets(cic_file):
    """parse() = parse_sheet() × N feuilles → total 3 + 2 = 5 transactions."""
    connector = CICConnector()
    transactions = connector.parse(cic_file)
    assert len(transactions) == 5
