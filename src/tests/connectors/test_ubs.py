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

import logging

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


# =============================================================================
# _clean_merchant() — nettoyage des préfixes UBS parasites
# =============================================================================


def test_clean_merchant_strips_gutschrift_prefix():
    """'Gutschrift ANTEIS SA' → 'ANTEIS SA'"""
    c = UBSConnector()
    assert c._clean_merchant("Gutschrift ANTEIS SA") == "ANTEIS SA"


def test_clean_merchant_strips_auftrag_prefix():
    """'Auftrag: Loyer appartement' → 'LOYER APPARTEMENT'"""
    c = UBSConnector()
    assert c._clean_merchant("Auftrag: Loyer appartement") == "LOYER APPARTEMENT"


def test_clean_merchant_strips_ebanking_prefix():
    """'E-Banking Virement Alvarez' → 'VIREMENT ALVAREZ'"""
    c = UBSConnector()
    assert c._clean_merchant("E-Banking Virement Alvarez") == "VIREMENT ALVAREZ"


def test_clean_merchant_strips_debit_direct_prefix():
    """'Debit Direct Swisscom' → 'SWISSCOM'"""
    c = UBSConnector()
    assert c._clean_merchant("Debit Direct Swisscom") == "SWISSCOM"


def test_clean_merchant_leaves_normal_merchant_intact():
    """Un nom de marchand sans préfixe UBS ne doit pas être modifié (hors casse)."""
    c = UBSConnector()
    assert c._clean_merchant("FEEL EAT SARL") == "FEEL EAT SARL"


def test_clean_merchant_collapses_spaces():
    """Les espaces multiples (padding UBS) doivent être réduits à un seul."""
    c = UBSConnector()
    assert (
        c._clean_merchant("FEEL EAT SARL            LA CHAUX-D")
        == "FEEL EAT SARL LA CHAUX-D"
    )


# =============================================================================
# Renommage de colonne UBS : « Monnaie » → « Devise » (#setup-local)
#
# UBS a renommé la colonne de devise dans ses exports. Le connecteur attendait
# « Monnaie » à deux endroits, avec deux conséquences très différentes :
#   1. COLUMN_SIGNATURE : matches_file() renvoyait False → fichier IGNORÉ en
#      silence, aucun message, aucune trace.
#   2. _parse_amount()  : row.get("Monnaie") → currency="" sur TOUTES les lignes.
#      Bien plus grave, parce que muet : les transactions seraient entrées en
#      base sans devise, et services.exchange_rates.to_chf (porte unique de
#      conversion) aurait produit des montants faux sans lever d'erreur.
#
# Les DEUX formats doivent passer : le dossier d'archives contient des exports
# à l'ancien format, qui doivent rester réimportables.
# =============================================================================


def test_matches_file_accepts_new_devise_header(ubs_csv_devise_path):
    """Le nouveau format (colonne « Devise ») doit être reconnu."""
    assert UBSConnector.matches_file(ubs_csv_devise_path) is True


def test_matches_file_still_accepts_legacy_monnaie_header(ubs_csv_path):
    """Non-régression : l'ancien format (« Monnaie ») reste reconnu."""
    assert UBSConnector.matches_file(ubs_csv_path) is True


def test_parse_new_format_returns_same_transactions(ubs_csv_devise_path):
    """Le nouveau format contient les mêmes 3 transactions que l'ancien."""
    transactions = UBSConnector().parse(ubs_csv_devise_path)
    assert len(transactions) == 3


def test_parse_new_format_sets_currency(ubs_csv_devise_path):
    """
    Le bug MUET : sans lecture de « Devise », currency valait "" sur chaque ligne.

    On assert sur la valeur réelle, pas sur « la clé existe » — une chaîne vide
    aurait satisfait un test plus faible tout en corrompant la conversion CHF.
    """
    transactions = UBSConnector().parse(ubs_csv_devise_path)
    assert [tx["currency"] for tx in transactions] == ["CHF", "CHF", "CHF"]


def test_parse_both_formats_produce_identical_output(ubs_csv_path, ubs_csv_devise_path):
    """
    Ancien et nouveau format décrivent les mêmes écritures → même sortie.

    Compare les dicts entiers : si un jour le renommage touche une AUTRE colonne,
    ce test le voit, alors qu'un test ciblé sur `currency` ne le verrait pas.
    """
    connector = UBSConnector()
    assert connector.parse(ubs_csv_path) == connector.parse(ubs_csv_devise_path)


# =============================================================================
# Compte d'épargne sans mouvement — export légitime, ne doit rien casser
# =============================================================================


def test_matches_file_accepts_empty_savings_export(ubs_csv_empty_savings_path):
    """Un relevé d'épargne à 0 transaction reste un relevé UBS valide."""
    assert UBSConnector.matches_file(ubs_csv_empty_savings_path) is True


def test_parse_empty_savings_returns_no_transaction(ubs_csv_empty_savings_path):
    """Zéro ligne de données → liste vide, pas une exception."""
    assert UBSConnector().parse(ubs_csv_empty_savings_path) == []


def test_extract_balance_returns_none_when_balance_field_is_empty(
    ubs_csv_empty_savings_path, caplog
):
    """
    « Solde final:;; » (champ vide) → None, sans lever ni logger de stacktrace.

    Un solde absent est une donnée manquante NORMALE sur un compte sans
    mouvement — pas une anomalie à signaler bruyamment.

    On assert AUSSI sur l'absence de log : la version fautive renvoyait déjà
    None (l'exception était rattrapée), donc un test qui se contente du None
    passait au vert tout en laissant une stacktrace à chaque import.
    """
    with caplog.at_level(logging.WARNING, logger="connectors.ubs.parser"):
        assert UBSConnector().extract_balance(ubs_csv_empty_savings_path) is None
    assert caplog.records == []


def test_extract_balance_reads_final_not_initial_balance(ubs_csv_devise_path):
    """
    « Solde initial » précède « Solde final » — on doit lire le second.

    Garde-fou du repérage par libellé : un startswith trop large attraperait
    « Solde initial:;0.00; » et renverrait 0.00 au lieu de 12000.00.
    """
    assert UBSConnector().extract_balance(ubs_csv_devise_path) == 12000.00


def test_extract_account_identifier_works_on_empty_savings(
    ubs_csv_empty_savings_path,
):
    """L'IBAN reste lisible même sans transaction — c'est lui qui résout le compte."""
    identifier = UBSConnector().extract_account_identifier(ubs_csv_empty_savings_path)
    assert identifier == "CH0000000000000000001"
