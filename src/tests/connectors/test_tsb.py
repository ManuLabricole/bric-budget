"""
tests/connectors/test_tsb.py — Tests unitaires de TSBConnector.

Tests PURS PYTHON — aucun accès à la base de données.

Fixture CSV (tsb_sample.csv) — 9 transactions choisies pour couvrir les pièges
que l'analyse des 831 lignes réelles a fait apparaître :

    2× FIRST GLASGOW le même jour, même montant, même libellé  → occurrence_index
    ACME REFUND en DEB mais colonne Crédit remplie             → le TYPE ne donne
    ROOMIE BILLS en SO mais colonne Crédit remplie                pas le sens
    DEBIT INTEREST → solde -38.79                              → découvert légitime
    PLAIN MERCHANT à « 3 » (sans décimales)                     → normalisation
    « CD 1234 09FEB26 » sans nom de marchand                    → display_name non vide
    « 2.99% CD 0000 23APR26 » frais de change carte étrangère   → display_name pas
                                                                   juste "2.99%"
    ordre ANTI-chronologique (17/03 en tête)                    → solde de clôture
                                                                   sur la 1re ligne
"""

import hashlib

from connectors.tsb.parser import TSBConnector

# =============================================================================
# matches_file() — détection du format
# =============================================================================


def test_matches_file_true_for_tsb_csv(tsb_csv_path):
    assert TSBConnector.matches_file(tsb_csv_path) is True


def test_matches_file_false_for_ubs_csv(ubs_csv_path):
    """Un CSV UBS ne doit jamais être happé par TSB (les deux sont des .csv)."""
    assert TSBConnector.matches_file(ubs_csv_path) is False


def test_matches_file_false_for_yuh_csv(yuh_csv_path):
    assert TSBConnector.matches_file(yuh_csv_path) is False


def test_other_connectors_reject_tsb_csv(tsb_csv_path):
    """
    Réciproque : aucun connecteur existant ne doit revendiquer un CSV TSB.

    detect_connector prend le PREMIER qui répond True — une revendication
    concurrente ferait parser du TSB par le mauvais connecteur selon l'ordre
    de la liste, un bug qui ne se verrait qu'à l'exécution.
    """
    from connectors.ubs.parser import UBSConnector
    from connectors.yuh.parser import YuhConnector

    assert UBSConnector.matches_file(tsb_csv_path) is False
    assert YuhConnector.matches_file(tsb_csv_path) is False


# =============================================================================
# parse() — montants et direction
# =============================================================================


def test_parse_returns_all_rows(tsb_csv_path):
    """Aucun type TSB n'est filtré : les 9 lignes sont de vraies transactions."""
    assert len(TSBConnector().parse(tsb_csv_path)) == 9


def test_debit_is_negative(tsb_csv_path):
    transactions = TSBConnector().parse(tsb_csv_path)
    assert transactions[0]["amount"] == -5.95


def test_credit_is_positive(tsb_csv_path):
    transactions = TSBConnector().parse(tsb_csv_path)
    assert transactions[2]["amount"] == 156.51


def test_direction_comes_from_the_column_not_the_type(tsb_csv_path):
    """
    LE piège TSB : « Transaction Type » ne donne PAS le sens.

    Sur les données réelles, 3 lignes DEB et 2 lignes SO sont des CRÉDITS
    (remboursements carte, partage de charges). Un connecteur qui ferait
    `if type == "DEB": amount = -x` transformerait un remboursement de
    156.51 en dépense — une erreur invisible qui fausse tout le budget.
    """
    transactions = TSBConnector().parse(tsb_csv_path)
    deb_credit = transactions[2]  # DEB, mais colonne Crédit remplie
    so_credit = transactions[3]  # SO, mais colonne Crédit remplie

    assert deb_credit["amount"] > 0, "un DEB peut être un crédit (remboursement)"
    assert so_credit["amount"] > 0, "un SO peut être un crédit (partage de charges)"


def test_currency_is_gbp(tsb_csv_path):
    """
    TSB n'exporte AUCUNE colonne de devise — « GBP » est une hypothèse du
    connecteur, assumée explicitement. Ce test la fige : si un jour TSB
    exporte un compte dans une autre devise, il échoue et force la décision.
    """
    transactions = TSBConnector().parse(tsb_csv_path)
    assert {tx["currency"] for tx in transactions} == {"GBP"}


def test_dates_are_iso(tsb_csv_path):
    from datetime import date

    for tx in TSBConnector().parse(tsb_csv_path):
        date.fromisoformat(tx["date"])  # lève si le format n'est pas ISO


def test_time_is_always_none(tsb_csv_path):
    """TSB n'exporte pas l'heure — contrairement à UBS."""
    assert all(tx["time"] is None for tx in TSBConnector().parse(tsb_csv_path))


# =============================================================================
# balance_after — présent sur chaque ligne (comme CIC)
# =============================================================================


def test_balance_after_is_set_on_every_row(tsb_csv_path):
    """
    100 % des lignes TSB portent le solde courant → snapshots quotidiens.
    C'est ce qui distingue TSB de Yuh/UBS, qui n'ont qu'un solde de clôture.
    """
    transactions = TSBConnector().parse(tsb_csv_path)
    assert all(tx["balance_after"] is not None for tx in transactions)
    assert transactions[0]["balance_after"] == 382.29


def test_negative_balance_is_preserved(tsb_csv_path):
    """
    Un solde négatif est un DÉCOUVERT légitime, pas une anomalie à corriger.
    Le clamper à 0 fausserait la courbe de patrimoine en masquant le découvert.
    """
    transactions = TSBConnector().parse(tsb_csv_path)
    assert transactions[5]["balance_after"] == -38.79


# =============================================================================
# extract_balance() — l'ordre du fichier est ANTI-chronologique
# =============================================================================


def test_extract_balance_reads_the_most_recent_row(tsb_csv_path):
    """
    TSB liste la transaction la PLUS RÉCENTE en premier (vérifié sur 10/10
    fichiers réels). Le solde de clôture est donc sur la PREMIÈRE ligne de
    données — lire la dernière renverrait le solde d'ouverture de la période.
    """
    assert TSBConnector().extract_balance(tsb_csv_path) == 382.29


# =============================================================================
# extract_account_identifier() — Sort Code + Account Number
# =============================================================================


def test_extract_account_identifier_concatenates_sortcode_and_number(tsb_csv_path):
    """
    L'identité TSB est le sort code SANS tirets, suivi du n° de compte.
    C'est la forme stockée dans Account.contract_number — les deux côtés
    doivent employer exactement la même normalisation, sinon aucun match.
    """
    assert TSBConnector().extract_account_identifier(tsb_csv_path) == "00000000000000"


def test_identity_is_exposed_as_a_single_account(tsb_csv_path):
    """Un export TSB = un seul compte (contrairement au multi-feuilles CIC)."""
    identities = TSBConnector().list_account_identities(tsb_csv_path)
    assert len(identities) == 1
    assert identities[0].identifier == "00000000000000"


# =============================================================================
# card_last_four
# =============================================================================


def test_card_last_four_extracted_from_description(tsb_csv_path):
    """Les paiements carte encastrent « CD <4 chiffres > » en fin de libellé."""
    transactions = TSBConnector().parse(tsb_csv_path)
    assert transactions[0]["card_last_four"] == "1234"


def test_card_last_four_is_none_without_marker(tsb_csv_path):
    transactions = TSBConnector().parse(tsb_csv_path)
    assert transactions[4]["card_last_four"] is None  # SOME UTILITY, pas une carte


# =============================================================================
# display_name — jamais vide
# =============================================================================


def test_display_name_is_never_empty(tsb_csv_path):
    """
    Un libellé réel peut ne contenir AUCUN nom de marchand (« CD 1234 09FEB26 »).
    Un nettoyage qui retirerait le marqueur de carte et la date produirait une
    chaîne vide — la transaction deviendrait alors impossible à reconnaître dans
    l'UI et inutilisable par les règles de catégorisation.
    """
    for tx in TSBConnector().parse(tsb_csv_path):
        assert tx["display_name"].strip(), (
            f"display_name vide pour {tx['description_raw']!r}"
        )


def test_merchant_name_mirrors_display_name(tsb_csv_path):
    """merchant_name = copie de display_name à l'import (override user ensuite)."""
    for tx in TSBConnector().parse(tsb_csv_path):
        assert tx["merchant_name"] == tx["display_name"]


def test_fx_fee_description_is_not_left_as_bare_percentage(tsb_csv_path):
    """
    « 2.99% CD 0000 23APR26 » : retirer le marqueur carte laisse "2.99%" —
    non vide, donc l'ancien repli (cleaned or description) ne se déclenchait
    PAS, et l'UI affichait une ligne illisible ("2.99%" sans aucun contexte).

    Le nouveau repli élargi (aucune lettre → on garde le libellé brut complet)
    doit préserver "CD 0000 23APR26" plutôt que produire "2.99%" tout seul —
    quitte à laisser plus d'info que nécessaire, jamais moins.
    """
    tx = next(
        t
        for t in TSBConnector().parse(tsb_csv_path)
        if t["description_raw"] == "2.99% CD 0000 23APR26"
    )
    assert tx["display_name"] != "2.99%"
    assert "2.99%" in tx["display_name"]
    assert "CD 0000" in tx["display_name"]
    # card_last_four reste extrait normalement — le repli ne touche que
    # display_name, pas _parse_card() (regex indépendante).
    assert tx["card_last_four"] == "0000"


# =============================================================================
# import_hash — UNIQUE et STABLE (le CONTRAT de base.py)
# =============================================================================


def test_import_hashes_are_unique(tsb_csv_path):
    transactions = TSBConnector().parse(tsb_csv_path)
    hashes = [tx["import_hash"] for tx in transactions]
    assert len(set(hashes)) == len(hashes)


def test_two_identical_same_day_transactions_get_distinct_hashes(tsb_csv_path):
    """
    Les 2 « FIRST GLASGOW » du 17/03 sont deux VRAIS trajets, pas un doublon.

    Sans occurrence_index, ils partagent date + type + montant + libellé et
    l'un des deux serait avalé silencieusement. Mesuré sur les données réelles :
    13 collisions, soit 19 transactions perdues.
    """
    transactions = TSBConnector().parse(tsb_csv_path)
    assert transactions[0]["description_raw"] == transactions[1]["description_raw"]
    assert transactions[0]["amount"] == transactions[1]["amount"]
    assert transactions[0]["import_hash"] != transactions[1]["import_hash"]


def test_hash_ignores_amount_formatting(tsb_csv_path):
    """
    « 3 » et « 3.00 » doivent produire le MÊME hash.

    TSB écrit aujourd'hui « 3 » ; le jour où un export écrit « 3.00 », un hash
    construit sur le texte brut re-hacherait tout l'historique et le
    réimporterait en doublons. Le montant est donc normalisé en Decimal à 2
    décimales AVANT hachage — la seule protection contre un changement de
    formatage côté banque.
    """
    connector = TSBConnector()
    row_terse = {
        "Transaction date": "2026-03-12",
        "Transaction Type": "DEB",
        "Sort Code": "00-00-00",
        "Account Number": "00000000",
        "Transaction description": "PLAIN MERCHANT NO CARD",
        "Debit Amount": "3",
        "Credit amount": "",
        "Balance": "-38.71",
    }
    row_padded = {**row_terse, "Debit Amount": "3.00"}

    terse = connector._parse_row(row_terse, {})
    padded = connector._parse_row(row_padded, {})
    assert terse["import_hash"] == padded["import_hash"]


def test_hash_is_stable_across_overlapping_exports(tsb_csv_path):
    """
    La propriété STABLE du contrat : la même transaction, vue dans deux exports
    qui se chevauchent, produit le même hash.

    On simule le recouvrement en reparsant un sous-ensemble du fichier — c'est
    le cas réel d'un export mensuel qui recoupe un export trimestriel. Mesuré
    sur les 831 lignes réelles (136 transactions communes) : 0 instabilité.
    """
    connector = TSBConnector()
    full = connector.parse(tsb_csv_path)

    # Re-parse des mêmes lignes dans un compteur d'occurrences neuf : c'est ce
    # que fait un second export contenant la même journée.
    counters: dict = {}
    rows = [
        {
            "Transaction date": tx["date"],
            "Transaction Type": "DEB",
            "Sort Code": "00-00-00",
            "Account Number": "00000000",
            "Transaction description": tx["description_raw"],
            "Debit Amount": f"{-tx['amount']:.2f}" if tx["amount"] < 0 else "",
            "Credit amount": f"{tx['amount']:.2f}" if tx["amount"] > 0 else "",
            "Balance": str(tx["balance_after"]),
        }
        for tx in full[:2]  # les 2 FIRST GLASGOW : le cas le plus exigeant
    ]
    replayed = [connector._parse_row(r, counters) for r in rows]

    assert [t["import_hash"] for t in replayed] == [t["import_hash"] for t in full[:2]]


def test_hash_is_sha256_hex(tsb_csv_path):
    for tx in TSBConnector().parse(tsb_csv_path):
        assert len(tx["import_hash"]) == len(hashlib.sha256(b"").hexdigest())
        int(tx["import_hash"], 16)  # lève si ce n'est pas de l'hexadécimal
