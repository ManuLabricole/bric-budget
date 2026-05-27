"""
tests/connectors/test_hash_stability.py

Tests de stabilité des import_hash — la propriété la plus critique du système.

Un hash instable = doublons lors des re-imports = données corrompues.

Pour chaque connecteur, on vérifie deux propriétés :
  STABLE  : même transaction dans deux exports différents → même hash
  UNIQUE  : deux transactions distinctes → hashes différents

Connecteurs testés :
  A. Yuh  — occurrence_index (stable cross-export)
  B. CIC  — contenu sans row_idx (stable cross-export antichronologique)
  C. UBS  — No de transaction (stable, bank-guaranteed)

Ces tests sont PURS PYTHON — aucune base de données nécessaire.
"""

import hashlib
from datetime import datetime

import pytest

from connectors.cic.parser import CICConnector
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector

# =============================================================================
# A. Yuh — occurrence_index
# =============================================================================


def _yuh_row(
    date="17/03/2026", activity_type="PAYMENT", name="Parking Gare", amount="2.00"
):
    """Crée un dict de ligne CSV Yuh minimal."""
    return {
        "DATE": date,
        "ACTIVITY TYPE": activity_type,
        "ACTIVITY NAME": name,
        "DEBIT": amount,
        "CREDIT": "",
        "CURRENCY": "CHF",
        "CARD NUMBER": "",
    }


def test_yuh_same_transaction_same_hash_regardless_of_line_number():
    """
    La même transaction (même contenu) produit le même hash quel que soit
    son numéro de ligne dans le fichier.

    AVANT (bug) : hash incluait line_number → export partiel = lignes décalées = doublons.
    APRÈS (fix)  : hash basé sur occurrence_index dans le groupe (date, type, amount, desc).

    Scénario :
      Export complet → parking à la ligne 45.
      Export mensuel → même parking à la ligne 3.
      Les deux doivent produire le même hash.
    """
    connector = YuhConnector()
    row = _yuh_row()

    counters_full_export: dict[str, int] = {}
    tx_line_45 = connector._parse_row(
        row, line_number=45, occurrence_counters=counters_full_export
    )

    counters_monthly_export: dict[str, int] = {}
    tx_line_3 = connector._parse_row(
        row, line_number=3, occurrence_counters=counters_monthly_export
    )

    assert tx_line_45["import_hash"] == tx_line_3["import_hash"]


def test_yuh_two_identical_transactions_same_day_get_different_hashes():
    """
    Deux transactions strictement identiques le même jour (ex: deux parkings 2 CHF)
    doivent avoir des hashes différents grâce à occurrence_index.

    Sans occurrence_index : même hash → unique constraint violation à l'import.
    Avec occurrence_index  : 1er = index 0, 2ème = index 1 → hashes distincts.
    """
    connector = YuhConnector()
    row = _yuh_row()

    counters: dict[str, int] = {}
    tx1 = connector._parse_row(row, line_number=1, occurrence_counters=counters)
    tx2 = connector._parse_row(row, line_number=2, occurrence_counters=counters)

    assert tx1["import_hash"] != tx2["import_hash"]


def test_yuh_occurrence_index_stable_across_partial_exports():
    """
    Scénario réel : import mensuel janvier, puis import mensuel février,
    puis import full year. Pas de doublons attendus.

    On simule deux transactions récurrentes (loyer) en janvier :
    - Export janv : loyer à la ligne 1
    - Export full : loyer à la ligne 45

    L'occurrence_index est 0 dans les deux cas (premier loyer vu dans ce fichier).
    """
    connector = YuhConnector()
    loyer = _yuh_row(
        date="15/01/2026",
        activity_type="PAYMENT_TRANSACTION_OUT",
        name="VIREMENT LOYER",
        amount="1200.00",
    )

    # Import partiel janvier
    counters_jan: dict[str, int] = {}
    tx_jan = connector._parse_row(
        loyer, line_number=1, occurrence_counters=counters_jan
    )

    # Import full year — loyer est à la ligne 45 mais c'est toujours le 1er du groupe
    counters_full: dict[str, int] = {}
    tx_full = connector._parse_row(
        loyer, line_number=45, occurrence_counters=counters_full
    )

    assert tx_jan["import_hash"] == tx_full["import_hash"]


def test_yuh_occurrence_index_increments_correctly_for_repeated_transactions():
    """
    Dans un fichier avec 3 parkings identiques, les occurrence_index sont 0, 1, 2.
    Ces index sont stables entre un export complet et un export mensuel.

    Ici on simule le fichier mensuel seul : les 3 parkings sont aux lignes 1, 2, 3.
    Dans le fichier complet ils seraient aux lignes 50, 51, 52.
    Les hashes doivent être identiques dans les deux cas.
    """
    connector = YuhConnector()
    row = _yuh_row(name="Parking Migros")

    # Fichier mensuel : lignes 1, 2, 3
    counters_monthly: dict[str, int] = {}
    monthly_hashes = [
        connector._parse_row(row, line_number=i, occurrence_counters=counters_monthly)[
            "import_hash"
        ]
        for i in range(1, 4)
    ]

    # Fichier complet : lignes 50, 51, 52
    counters_full: dict[str, int] = {}
    full_hashes = [
        connector._parse_row(row, line_number=i, occurrence_counters=counters_full)[
            "import_hash"
        ]
        for i in range(50, 53)
    ]

    assert monthly_hashes == full_hashes


def test_yuh_different_amounts_produce_different_hashes():
    """Deux transactions mêmes date/type/desc mais montants différents → hashes différents."""
    connector = YuhConnector()

    counters: dict[str, int] = {}
    tx_2chf = connector._parse_row(
        _yuh_row(amount="2.00"), line_number=1, occurrence_counters=counters
    )
    tx_3chf = connector._parse_row(
        _yuh_row(amount="3.00"), line_number=2, occurrence_counters=counters
    )

    assert tx_2chf["import_hash"] != tx_3chf["import_hash"]


def test_yuh_balance_after_is_none():
    """Yuh n'a pas de solde par ligne → balance_after doit être None."""
    connector = YuhConnector()
    tx = connector._parse_row(_yuh_row(), line_number=1, occurrence_counters={})
    assert tx["balance_after"] is None


# =============================================================================
# B. CIC — hash sans row_idx
# =============================================================================


def _cic_row_kwargs(
    date_val=None,
    libelle="PAIEMENT PSC 1703 GRENOBLE FNAC CARTE 8703",
    debit=-45.0,
    credit=None,
    solde=1234.56,
    currency="EUR",
    rib="10096XXXXXXXXXXXXXXXXXXX",
):
    """Kwargs pour CICConnector._parse_row."""
    if date_val is None:
        date_val = datetime(2026, 3, 17)
    return dict(
        date_val=date_val,
        libelle=libelle,
        debit=debit,
        credit=credit,
        solde=solde,
        currency=currency,
        rib=rib,
        row_idx=6,
    )


def test_cic_hash_stable_across_different_row_positions():
    """
    Le hash CIC ne doit PAS dépendre de row_idx (position dans l'Excel).

    AVANT (bug) : hash incluait row_idx → nouvel export avec nouvelles transactions
                  en tête décalait toutes les lignes → doublons à chaque re-import.
    APRÈS (fix)  : hash = sha256(rib|date|amount|description|occurrence_index).

    On passe row_idx=6 et row_idx=100 avec des compteurs indépendants (occurrence_index=0
    dans les deux cas) — le hash doit être identique.
    """
    connector = CICConnector()

    kwargs = _cic_row_kwargs()
    tx_row6 = connector._parse_row(**{**kwargs, "row_idx": 6})
    tx_row100 = connector._parse_row(**{**kwargs, "row_idx": 100})

    assert tx_row6["import_hash"] == tx_row100["import_hash"]


def test_cic_two_identical_transactions_same_day_get_different_hashes():
    """
    Deux transactions CIC strictement identiques le même jour (ex: deux tickets RATP
    à 2.10€) doivent avoir des hashes différents grâce à occurrence_index.

    Cas réel : comptes.xlsx contient 53 paires de ce type (RATP, Amazon, bars...).
    Sans occurrence_index : contrainte unique import_hash → IntegrityError.
    Avec occurrence_index  : 1ère = index 0, 2ème = index 1 → hashes distincts.
    """
    connector = CICConnector()
    counters: dict[str, int] = {}
    kwargs = _cic_row_kwargs(libelle="RATP", debit=-2.1)

    tx1 = connector._parse_row(**{**kwargs}, occurrence_counters=counters)
    tx2 = connector._parse_row(**{**kwargs}, occurrence_counters=counters)

    assert tx1["import_hash"] != tx2["import_hash"]


def test_cic_occurrence_index_stable_across_partial_exports():
    """
    La 1ère occurrence d'une transaction a toujours occurrence_index=0, quelle que
    soit sa position dans le fichier (export partiel ou complet).

    Scénario : même ticket RATP à 2.10€ le 2026-03-17
      - Export complet : ticket à la ligne 150
      - Export mensuel : ticket à la ligne 8
    Les deux doivent produire le même hash (occurrence_index=0 dans les deux cas).
    """
    connector = CICConnector()
    kwargs = _cic_row_kwargs(libelle="RATP", debit=-2.1)

    counters_full: dict[str, int] = {}
    tx_full = connector._parse_row(
        **{**kwargs, "row_idx": 150}, occurrence_counters=counters_full
    )

    counters_monthly: dict[str, int] = {}
    tx_monthly = connector._parse_row(
        **{**kwargs, "row_idx": 8}, occurrence_counters=counters_monthly
    )

    assert tx_full["import_hash"] == tx_monthly["import_hash"]


def test_cic_hash_includes_rib_for_cross_account_uniqueness():
    """
    Deux comptes CIC (ex: C/C et Livret A) peuvent avoir la même transaction
    le même jour avec le même montant (ex: virement interne 500€).
    Le RIB dans le hash garantit que ces deux transactions ont des hashes distincts.
    """
    connector = CICConnector()

    kwargs = _cic_row_kwargs(
        libelle="VIR SEPA VIREMENT INTERNE", debit=None, credit=500.0
    )
    tx_cc = connector._parse_row(**{**kwargs, "rib": "1009618027CC0000001"})
    tx_livret = connector._parse_row(**{**kwargs, "rib": "1009618027LA0000001"})

    assert tx_cc["import_hash"] != tx_livret["import_hash"]


def test_cic_balance_after_extracted_from_solde_column():
    """
    Le solde de la colonne F (Solde après transaction) doit être retourné
    dans balance_after pour permettre les BalanceSnapshots journaliers.
    """
    connector = CICConnector()
    tx = connector._parse_row(**_cic_row_kwargs(solde=2456.78))
    assert tx["balance_after"] == 2456.78


def test_cic_balance_after_is_none_when_solde_is_none():
    """
    Certaines lignes CIC peuvent avoir la colonne Solde vide → balance_after=None.
    Le parser ne doit pas crasher dans ce cas.
    """
    connector = CICConnector()
    tx = connector._parse_row(**_cic_row_kwargs(solde=None))
    assert tx["balance_after"] is None


def test_cic_debit_amount_is_negative():
    """Colonne Débit (négatif dans le fichier) → amount négatif dans TransactionDict."""
    connector = CICConnector()
    tx = connector._parse_row(**_cic_row_kwargs(debit=-123.45, credit=None))
    assert tx["amount"] == -123.45


def test_cic_credit_amount_is_positive():
    """Colonne Crédit → amount positif."""
    connector = CICConnector()
    tx = connector._parse_row(**_cic_row_kwargs(debit=None, credit=500.0))
    assert tx["amount"] == 500.0


def test_cic_raises_if_both_debit_and_credit_are_none():
    """Si les deux colonnes Débit et Crédit sont None, le parser doit lever ValueError."""
    connector = CICConnector()
    with pytest.raises(ValueError, match="None"):
        connector._parse_row(**_cic_row_kwargs(debit=None, credit=None))


def test_cic_card_last_four_extracted_from_carte_suffix():
    """'PAIEMENT PSC 1703 FNAC CARTE 8703' → card_last_four='8703'."""
    connector = CICConnector()
    tx = connector._parse_row(
        **_cic_row_kwargs(libelle="PAIEMENT PSC 1703 FNAC CARTE 8703")
    )
    assert tx["card_last_four"] == "8703"


def test_cic_card_last_four_is_none_for_transfer():
    """Un virement SEPA n'a pas de CARTE dans la description → card_last_four=None."""
    connector = CICConnector()
    tx = connector._parse_row(
        **_cic_row_kwargs(libelle="VIR SEPA SALAIRE EMPLOYEUR SA")
    )
    assert tx["card_last_four"] is None


# =============================================================================
# C. UBS — No de transaction
# =============================================================================


def _ubs_row(
    no_transaction="9999125BN1308361", description1="FEEL EAT SARL", amount="-45.00"
):
    """Crée un dict de ligne CSV UBS minimal."""
    return {
        "Date de transaction": "2026-03-17",
        "Heure de transaction": "12:30:00",
        "Date de comptabilisation": "2026-03-18",
        "Date de valeur": "2026-03-18",
        "Monnaie": "CHF",
        "Débit": amount,
        "Crédit": "",
        "Sous-montant": "",
        "Solde": "",
        "No de transaction": no_transaction,
        "Description1": description1,
        "Description2": "21303625-0 12/28; Paiement carte de debit",
        "Description3": f"No de transaction: {no_transaction}",
        "Notes de bas de page": "",
    }


def test_ubs_hash_uses_no_de_transaction_when_present():
    """
    Quand No de transaction est présent, le hash doit être sha256("ubs_tx|{id}").

    Cela signifie que même si la description change d'un export à l'autre
    (ex: padding variable), le hash reste stable car il ne dépend que de l'ID banque.
    """
    connector = UBSConnector()

    row_v1 = _ubs_row(description1="FEEL EAT SARL")
    row_v2 = _ubs_row(description1="FEEL EAT SARL            ")  # padding différent

    tx1 = connector._parse_row(row_v1)
    tx2 = connector._parse_row(row_v2)

    # Même No de transaction → même hash malgré description différente
    assert tx1["import_hash"] == tx2["import_hash"]


def test_ubs_hash_stable_for_same_no_de_transaction():
    """
    Deux appels avec le même No de transaction produisent toujours le même hash.
    Vérifie la formule : sha256("ubs_tx|" + no_transaction).
    """
    connector = UBSConnector()
    expected = hashlib.sha256("ubs_tx|9999125BN1308361".encode()).hexdigest()
    tx = connector._parse_row(_ubs_row(no_transaction="9999125BN1308361"))
    assert tx["import_hash"] == expected


def test_ubs_different_no_de_transaction_produces_different_hash():
    """Deux transactions avec des No de transaction différents → hashes différents."""
    connector = UBSConnector()
    tx1 = connector._parse_row(_ubs_row(no_transaction="9999125BN0000001"))
    tx2 = connector._parse_row(_ubs_row(no_transaction="9999125BN0000002"))
    assert tx1["import_hash"] != tx2["import_hash"]


def test_ubs_falls_back_to_content_hash_when_no_transaction_missing():
    """
    Sans No de transaction, le hash se base sur date|time|amount|desc1|desc2.
    Ce fallback ne doit pas crasher.
    """
    connector = UBSConnector()
    row = _ubs_row(no_transaction="")  # vide → fallback
    tx = connector._parse_row(row)
    assert len(tx["import_hash"]) == 64  # SHA256 hex = 64 chars


def test_ubs_balance_after_is_always_none():
    """
    UBS ne fournit pas de solde par ligne (seulement dans le header du fichier).
    balance_after doit toujours être None pour ce connecteur.
    """
    connector = UBSConnector()
    tx = connector._parse_row(_ubs_row())
    assert tx["balance_after"] is None


def test_ubs_time_is_set_for_card_transactions():
    """Les transactions carte UBS ont une heure → time doit être non-None."""
    connector = UBSConnector()
    tx = connector._parse_row(_ubs_row())
    assert tx["time"] == "12:30:00"


def test_ubs_time_is_none_for_transfers():
    """Les virements UBS n'ont pas d'heure → time doit être None."""
    connector = UBSConnector()
    row = _ubs_row()
    row["Heure de transaction"] = ""
    tx = connector._parse_row(row)
    assert tx["time"] is None
