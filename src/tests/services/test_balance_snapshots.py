"""
tests/services/test_balance_snapshots.py

Tests pour la création et la cohérence des BalanceSnapshots.

Deux mécanismes créent des snapshots dans ImportService :
  1. Daily snapshots  : depuis balance_after par ligne (CIC uniquement)
  2. Closing snapshot : depuis extract_balance() du connecteur (Yuh/UBS/CIC footer)

Comportements vérifiés :
  A. Daily snapshots créés depuis balance_after
  B. Pas de snapshots si 0 nouvelles transactions (tout skippé)
  C. update_or_create : ré-import même période → pas de doublon, valeur mise à jour
  D. balance_after None ne crée pas de snapshots (Yuh, UBS)
  E. Closing snapshot depuis balance parameter
  F. balance=None dans closing snapshot ne doit PAS écraser balance déjà peuplée
  G. computed_balance calculé depuis snapshot précédent
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from accounts.models import BalanceSnapshot
from tests.services.conftest import make_file_hash, make_tx
from transactions.services import ImportService

# =============================================================================
# Helpers
# =============================================================================


def make_tx_with_balance(seed, date_str, balance_after=None, amount=-10.0):
    """TransactionDict avec balance_after optionnel et date personnalisée."""
    import hashlib

    from connectors.base import TransactionDict

    import_hash = hashlib.sha256(f"snap:{seed}".encode()).hexdigest()
    return TransactionDict(
        date=date_str,
        time=None,
        amount=amount,
        currency="EUR",
        description_raw=f"TX {seed}",
        display_name=f"Shop {seed}",
        merchant_name=f"Shop {seed}",
        card_last_four=None,
        import_hash=import_hash,
        balance_after=balance_after,
    )


# =============================================================================
# A. Daily snapshots depuis balance_after
# =============================================================================


@pytest.mark.django_db
def test_daily_snapshots_created_from_balance_after(eur_account, user):
    """
    Quand les transactions ont un balance_after (CIC), un BalanceSnapshot est créé
    pour chaque date distincte.

    C'est la fonctionnalité principale : passer d'un seul snapshot par import
    à un snapshot par jour pour une courbe de solde complète.
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()
        transactions = [
            make_tx_with_balance("d1", "2026-03-01", balance_after=1500.0),
            make_tx_with_balance("d2", "2026-03-02", balance_after=1450.0),
            make_tx_with_balance("d3", "2026-03-03", balance_after=1400.0),
        ]
        service.run(
            transactions, eur_account, user, "cic.xlsx", make_file_hash("daily_a")
        )

    snapshots = BalanceSnapshot.objects.filter(account=eur_account).order_by("date")
    dates = list(snapshots.values_list("date", flat=True))

    from datetime import date

    assert date(2026, 3, 1) in dates
    assert date(2026, 3, 2) in dates
    assert date(2026, 3, 3) in dates


@pytest.mark.django_db
def test_daily_snapshot_balance_matches_balance_after(eur_account, user):
    """La valeur du snapshot = la valeur balance_after de la transaction."""
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()
        transactions = [
            make_tx_with_balance("val_check", "2026-03-15", balance_after=2345.67)
        ]
        service.run(transactions, eur_account, user, "cic.xlsx", make_file_hash("val"))

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=eur_account, date=date(2026, 3, 15))
    assert snap.balance == Decimal("2345.67")


@pytest.mark.django_db
def test_daily_snapshot_balance_chf_set_for_chf_account(chf_account, user):
    """Pour un compte CHF, balance_chf = balance (pas de conversion)."""
    service = ImportService()
    transactions = [
        make_tx_with_balance(
            "chf_snap", "2026-03-15", balance_after=5000.0, amount=-50.0
        )
    ]
    # Override currency to CHF
    transactions[0] = {**transactions[0], "currency": "CHF"}
    service.run(transactions, chf_account, user, "cic.xlsx", make_file_hash("chf_snap"))

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=chf_account, date=date(2026, 3, 15))
    assert snap.balance == Decimal("5000.0")
    assert snap.balance_chf == Decimal("5000.0")


@pytest.mark.django_db
def test_daily_snapshot_balance_chf_converted_for_eur_account(eur_account, user):
    """Compte EUR : balance_chf = balance × taux (converti comme amount_chf).

    RÉGRESSION (#118) : avant, le snapshot journalier laissait balance_chf=None
    pour les comptes non-CHF → patrimoine « Valorisation CHF partielle » et solde
    affiché « — ». Le solde DOIT être valorisé en CHF dès qu'un taux est dispo.
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()
        transactions = [
            make_tx_with_balance("eur_chf_conv", "2026-03-15", balance_after=1000.0)
        ]
        service.run(
            transactions, eur_account, user, "cic.xlsx", make_file_hash("eur_conv")
        )

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=eur_account, date=date(2026, 3, 15))
    assert snap.balance == Decimal("1000.0")
    assert snap.balance_chf == Decimal("930.00")  # 1000 × 0.93


@pytest.mark.django_db
def test_daily_snapshot_balance_chf_none_when_rate_unavailable(eur_account, user):
    """Compte EUR sans taux (API down) : balance_chf reste None — best effort.

    Symétrie avec amount_chf : on ne perd pas le snapshot, on le backfillera plus
    tard (commande backfill_chf). Le None n'est jamais un oubli de calcul, juste
    une indisponibilité réseau ponctuelle.
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=None,
    ):
        service = ImportService()
        transactions = [
            make_tx_with_balance("eur_chf_none", "2026-03-15", balance_after=1000.0)
        ]
        service.run(
            transactions, eur_account, user, "cic.xlsx", make_file_hash("eur_none")
        )

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=eur_account, date=date(2026, 3, 15))
    assert snap.balance == Decimal("1000.0")  # le solde brut est conservé
    assert snap.balance_chf is None


@pytest.mark.django_db
def test_cic_antichronological_first_seen_per_date_wins(eur_account, user):
    """
    CIC exporte en ordre antichronologique (plus récent en premier).
    Pour une date avec plusieurs transactions, la PREMIÈRE vue (= la plus récente
    chronologiquement = fin de journée) doit être le solde du snapshot.

    On passe les transactions dans l'ordre antichronologique pour simuler CIC.
    La 1ère transaction du jour (vue en premier) a le bon solde fin de journée.
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()
        transactions = [
            # Antichronologique : 3ème tx du jour vue en premier → solde fin de journée
            make_tx_with_balance(
                "tx3", "2026-03-10", balance_after=1200.0
            ),  # fin de journée
            make_tx_with_balance("tx2", "2026-03-10", balance_after=1230.0),
            make_tx_with_balance(
                "tx1", "2026-03-10", balance_after=1280.0
            ),  # début de journée
        ]
        service.run(
            transactions, eur_account, user, "cic.xlsx", make_file_hash("antichro")
        )

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=eur_account, date=date(2026, 3, 10))
    # Le premier vu (balance_after=1200) doit être retenu (fin de journée en antichronologique)
    assert snap.balance == Decimal("1200.0")


# =============================================================================
# B. Pas de snapshots si 0 nouvelles transactions
# =============================================================================


@pytest.mark.django_db
def test_no_daily_snapshots_when_all_transactions_skipped(eur_account, user):
    """
    Si toutes les transactions sont des doublons (skipped), aucun snapshot journalier
    ne doit être créé — même si les tx_dicts ont des balance_after valides.

    Logique : on ne génère pas de snapshots pour des données qu'on n'a pas "créées".
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()
        transactions = [
            make_tx_with_balance("dup_snap", "2026-03-15", balance_after=1000.0)
        ]

        # Premier import : crée la transaction
        service.run(
            transactions, eur_account, user, "file1.xlsx", make_file_hash("dup_s1")
        )
        BalanceSnapshot.objects.all().delete()  # reset snapshots

        # Deuxième import : tout skippé
        service.run(
            transactions, eur_account, user, "file2.xlsx", make_file_hash("dup_s2")
        )

    assert BalanceSnapshot.objects.count() == 0


# =============================================================================
# C. update_or_create — ré-import idempotent
# =============================================================================


@pytest.mark.django_db
def test_reimport_overlapping_period_updates_snapshot_not_duplicates(eur_account, user):
    """
    Ré-importer une période qui chevauche un import précédent doit mettre à jour
    les snapshots existants (update_or_create), pas en créer des doublons.

    Contrainte unique_together = [("account", "date")] doit être respectée.
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()

        # Premier import : solde 1000
        tx1 = make_tx_with_balance("overlap_1", "2026-03-15", balance_after=1000.0)
        service.run([tx1], eur_account, user, "file1.xlsx", make_file_hash("ovl1"))

        # Deuxième import : même date, nouveau fichier, solde corrigé 1050
        tx2 = make_tx_with_balance("overlap_2", "2026-03-15", balance_after=1050.0)
        service.run([tx2], eur_account, user, "file2.xlsx", make_file_hash("ovl2"))

    from datetime import date

    snapshots = BalanceSnapshot.objects.filter(
        account=eur_account, date=date(2026, 3, 15)
    )
    assert snapshots.count() == 1  # pas de doublon
    snap = snapshots.first()
    assert snap is not None
    assert snap.balance == Decimal("1050.0")  # valeur mise à jour


# =============================================================================
# D. balance_after=None → pas de snapshot journalier (Yuh, UBS)
# =============================================================================


@pytest.mark.django_db
def test_no_daily_snapshots_when_balance_after_is_none(chf_account, user):
    """
    Yuh et UBS retournent balance_after=None.
    Aucun snapshot journalier ne doit être créé depuis balance_after dans ce cas.

    Le seul snapshot éventuellement créé vient du closing snapshot (balance param).
    """
    service = ImportService()
    transactions = [
        make_tx("no_ba_1"),  # balance_after=None par défaut
        make_tx("no_ba_2"),
    ]
    # balance=None aussi → aucun snapshot du tout
    service.run(
        transactions,
        chf_account,
        user,
        "yuh.csv",
        make_file_hash("no_ba"),
        balance=None,
    )

    assert BalanceSnapshot.objects.count() == 0


# =============================================================================
# E. Closing snapshot depuis le paramètre balance
# =============================================================================


@pytest.mark.django_db
def test_closing_snapshot_created_from_balance_parameter(chf_account, user):
    """
    Le paramètre balance de ImportService.run() correspond au solde extrait du fichier
    (ex: footer CIC, header UBS, nom de fichier Yuh).
    Il doit créer un snapshot sur la date max des transactions.
    """
    service = ImportService()
    transactions = [
        {**make_tx("close_1"), "date": "2026-03-01"},
        {**make_tx("close_2"), "date": "2026-03-15"},
        {**make_tx("close_3"), "date": "2026-03-31"},
    ]
    service.run(
        transactions,  # type: ignore[arg-type]
        chf_account,
        user,
        "file.csv",
        make_file_hash("close"),
        balance=12345.67,
    )

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=chf_account, date=date(2026, 3, 31))
    assert snap.balance == Decimal("12345.67")


# =============================================================================
# F. balance=None dans closing snapshot ne doit pas écraser une bonne valeur
# =============================================================================


@pytest.mark.django_db
def test_closing_snapshot_with_none_balance_does_not_overwrite_daily_balance(
    eur_account, user
):
    """
    Scénario CIC : le parser extrait balance_after sur chaque ligne (journalier)
    MAIS le footer extraction peut échouer (balance=None dans extract_balance()).

    Dans ce cas, le closing snapshot block doit ajouter computed_balance sans
    écraser le balance déjà écrit par le daily snapshot.

    Régression : avant notre fix, "balance: None" dans update_or_create defaults
    écrasait la bonne valeur avec NULL.
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()

        # Transaction avec balance_after renseigné (colonne F CIC)
        tx = make_tx_with_balance("fix_overwrite", "2026-03-31", balance_after=3456.78)

        # balance=None simulant un footer CIC non extrait
        service.run(
            [tx], eur_account, user, "cic.xlsx", make_file_hash("fix_ow"), balance=None
        )

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=eur_account, date=date(2026, 3, 31))

    # Le balance du daily snapshot (3456.78) ne doit pas avoir été écrasé par None
    assert snap.balance == Decimal("3456.78")


# =============================================================================
# G. computed_balance calculé depuis snapshot précédent
# =============================================================================


@pytest.mark.django_db
def test_computed_balance_calculated_from_previous_snapshot(chf_account, user):
    """
    computed_balance = solde du dernier snapshot connu + somme des nouvelles transactions.

    Import 1 : balance=10000, crée snapshot date=15 mars avec balance=10000
    Import 2 : 3 transactions de -100, +200, -50 → computed = 10000 + (-100+200-50) = 10050
    """
    service = ImportService()

    # Import 1 : établit la baseline
    tx_baseline = [{**make_tx("base"), "date": "2026-03-15"}]
    service.run(
        tx_baseline,  # type: ignore[arg-type]
        chf_account,
        user,
        "file1.csv",
        make_file_hash("comp1"),
        balance=10000.0,
    )

    # Import 2 : nouvelles transactions à partir de mars 20
    txs_new = [
        make_tx("comp_a", date="2026-03-20", amount=-100.0),
        make_tx("comp_b", date="2026-03-21", amount=200.0),
        make_tx("comp_c", date="2026-03-22", amount=-50.0),
    ]
    service.run(
        txs_new,
        chf_account,
        user,
        "file2.csv",
        make_file_hash("comp2"),
        balance=None,  # type: ignore[arg-type]
    )

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=chf_account, date=date(2026, 3, 22))
    assert snap.computed_balance == Decimal("10050.00")


# =============================================================================
# H. Conversion CHF systématique du solde (régression #118 — « calculs oubliés »)
# =============================================================================


@pytest.mark.django_db
def test_closing_snapshot_balance_chf_converted_for_eur_account(eur_account, user):
    """Closing snapshot EUR : balance_chf = balance extrait × taux.

    Même oubli que le snapshot journalier : la clôture laissait balance_chf=None
    pour les comptes non-CHF. balance_after=None ici → on isole le closing pur
    (paramètre balance = footer extrait).
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.95"),
    ):
        service = ImportService()
        transactions = [
            make_tx_with_balance("eur_close", "2026-03-31", balance_after=None)
        ]
        service.run(
            transactions,
            eur_account,
            user,
            "cic.xlsx",
            make_file_hash("eur_close"),
            balance=2000.0,
        )

    from datetime import date

    snap = BalanceSnapshot.objects.get(account=eur_account, date=date(2026, 3, 31))
    assert snap.balance == Decimal("2000.0")
    assert snap.balance_chf == Decimal("1900.00")  # 2000 × 0.95


@pytest.mark.django_db
def test_no_snapshot_has_balance_without_balance_chf_when_rate_available(
    eur_account, user
):
    """Invariant anti-« calcul oublié » : aucun snapshot avec un solde mais sans
    balance_chf tant qu'un taux est dispo.

    Garde-fou : si une future branche de création de snapshot oublie la conversion
    CHF, ce test casse immédiatement (au lieu de laisser le patrimoine afficher « — »).
    """
    with patch(
        "services.exchange_rates.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        service = ImportService()
        transactions = [
            make_tx_with_balance("inv1", "2026-03-01", balance_after=1500.0),
            make_tx_with_balance("inv2", "2026-03-02", balance_after=1450.0),
        ]
        service.run(
            transactions,
            eur_account,
            user,
            "cic.xlsx",
            make_file_hash("invariant"),
            balance=1450.0,
        )

    orphans = BalanceSnapshot.objects.filter(
        account=eur_account, balance__isnull=False, balance_chf__isnull=True
    )
    assert not orphans.exists(), (
        f"{orphans.count()} snapshot(s) avec balance mais sans balance_chf alors "
        "qu'un taux est dispo — conversion CHF oubliée."
    )
