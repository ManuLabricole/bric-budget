"""
tests/services/test_cascade_and_signals.py

Tests pour le cycle de vie d'un ImportLog : création, suppression, effets en cascade.

Comportements vérifiés :
  A. CASCADE Transaction : supprimer ImportLog → transactions supprimées
  B. Signal snapshots    : snapshots orphelins supprimés après suppression ImportLog
  C. Signal shared       : snapshot partagé entre deux imports survit si l'autre import reste
  D. Signal no-op        : ImportLog sans date_min/max (0 transactions) ne crash pas
  E. date_min/date_max   : correctement peuplés après import
  F. date_min/date_max   : restent None si 0 nouvelles transactions
  G. log_pk              : ImportResult.log_pk pointe vers le bon ImportLog

Ces tests couvrent du code récent — CASCADE (migration 0012) et signals.py (nouveau).
"""

import hashlib
from datetime import date

import pytest

from accounts.models import BalanceSnapshot
from tests.services.conftest import make_file_hash, make_tx
from transactions.models import ImportLog, Transaction
from transactions.services import ImportService

# =============================================================================
# Helpers
# =============================================================================


def _create_import_log(account, user, date_min=None, date_max=None, file_seed="x"):
    """Crée un ImportLog directement en DB (sans passer par ImportService)."""
    return ImportLog.objects.create(
        account=account,
        imported_by=user,
        filename="test.csv",
        file_hash=make_file_hash(file_seed),
        status=ImportLog.Status.SUCCESS,
        date_min=date_min,
        date_max=date_max,
    )


def _create_transaction(account, import_log, tx_date, seed):
    """Crée une Transaction minimale liée à un ImportLog."""
    import_hash = hashlib.sha256(f"tx:{seed}".encode()).hexdigest()
    return Transaction.objects.create(
        account=account,
        import_log=import_log,
        date=tx_date,
        amount=-10,
        currency=account.currency,
        description_raw=f"TX {seed}",
        merchant_name=f"Shop {seed}",
        import_hash=import_hash,
    )


def _create_snapshot(account, snap_date, balance=1000):
    """Crée un BalanceSnapshot pour un (account, date)."""
    return BalanceSnapshot.objects.create(
        account=account,
        date=snap_date,
        balance=balance,
        currency=account.currency,
        source=BalanceSnapshot.Source.IMPORT,
    )


# =============================================================================
# A. CASCADE Transaction
# =============================================================================


@pytest.mark.django_db
def test_delete_import_log_cascades_to_transactions(chf_account, user):
    """
    Supprimer un ImportLog doit supprimer toutes ses transactions (CASCADE).

    Avant : on_delete=SET_NULL — les transactions restaient orphelines (import_log=NULL).
    Après : on_delete=CASCADE — les transactions sont supprimées avec le log.

    Pourquoi c'est important : un utilisateur qui supprime un import veut effacer
    toutes les données qu'il a introduites, pas laisser des transactions fantômes.
    """
    log = _create_import_log(chf_account, user, file_seed="cascade_a")
    _create_transaction(chf_account, log, date(2026, 3, 1), "t1")
    _create_transaction(chf_account, log, date(2026, 3, 2), "t2")
    _create_transaction(chf_account, log, date(2026, 3, 3), "t3")

    assert Transaction.objects.count() == 3
    log.delete()
    assert Transaction.objects.count() == 0


@pytest.mark.django_db
def test_delete_import_log_only_removes_its_own_transactions(chf_account, user):
    """
    La cascade ne touche que les transactions liées au log supprimé.

    Transactions d'un autre import (même compte) doivent rester intactes.
    """
    log1 = _create_import_log(chf_account, user, file_seed="cascade_b1")
    log2 = _create_import_log(chf_account, user, file_seed="cascade_b2")

    _create_transaction(chf_account, log1, date(2026, 3, 1), "t_log1")
    _create_transaction(chf_account, log2, date(2026, 4, 1), "t_log2")

    log1.delete()

    assert Transaction.objects.count() == 1
    assert Transaction.objects.filter(import_log=log2).count() == 1


@pytest.mark.django_db
def test_null_import_log_transactions_are_not_affected_by_other_deletions(
    chf_account, user
):
    """
    Les transactions sans import_log (import_log=NULL, créées en CLI) survivent
    à la suppression d'autres ImportLogs.

    import_log=NULL signifie "importée avant que le FK existait" ou "CLI sans log".
    Ces transactions sont précieuses et ne doivent jamais être supprimées par effet de bord.
    """
    log = _create_import_log(chf_account, user, file_seed="cascade_c")
    _create_transaction(chf_account, log, date(2026, 3, 1), "with_log")

    # Transaction orpheline (import_log=NULL)
    import_hash = hashlib.sha256(b"no_log_tx").hexdigest()
    Transaction.objects.create(
        account=chf_account,
        import_log=None,  # pas de log
        date=date(2026, 2, 1),
        amount=-5,
        currency="CHF",
        description_raw="OLD TX",
        merchant_name="Old",
        import_hash=import_hash,
    )

    log.delete()

    assert Transaction.objects.count() == 1
    assert Transaction.objects.filter(import_log=None).count() == 1


# =============================================================================
# B. Signal — snapshots orphelins supprimés
# =============================================================================


@pytest.mark.django_db
def test_delete_import_log_removes_orphaned_snapshot(chf_account, user):
    """
    Supprimer un ImportLog dont les dates ne sont couvertes par aucun autre import
    doit supprimer les BalanceSnapshots correspondants.

    Scénario : import unique pour mars → suppression → plus aucune tx en mars
    → snapshot mars supprimé.
    """
    snap_date = date(2026, 3, 15)
    log = _create_import_log(
        chf_account, user, date_min=snap_date, date_max=snap_date, file_seed="sig_a"
    )
    _create_transaction(chf_account, log, snap_date, "sig_t1")
    _create_snapshot(chf_account, snap_date)

    assert (
        BalanceSnapshot.objects.filter(account=chf_account, date=snap_date).count() == 1
    )

    log.delete()

    assert Transaction.objects.count() == 0
    assert (
        BalanceSnapshot.objects.filter(account=chf_account, date=snap_date).count() == 0
    )


@pytest.mark.django_db
def test_delete_import_log_removes_all_orphaned_snapshots_in_range(chf_account, user):
    """
    Si l'import couvrait plusieurs jours, tous les snapshots orphelins sont nettoyés.
    """
    d1, d2, d3 = date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)
    log = _create_import_log(
        chf_account, user, date_min=d1, date_max=d3, file_seed="sig_b"
    )
    _create_transaction(chf_account, log, d1, "b_t1")
    _create_transaction(chf_account, log, d2, "b_t2")
    _create_transaction(chf_account, log, d3, "b_t3")
    for d in [d1, d2, d3]:
        _create_snapshot(chf_account, d)

    log.delete()

    assert BalanceSnapshot.objects.filter(account=chf_account).count() == 0


# =============================================================================
# C. Signal — snapshot partagé survit si l'autre import reste
# =============================================================================


@pytest.mark.django_db
def test_shared_snapshot_survives_when_other_import_still_covers_date(
    chf_account, user
):
    """
    Deux imports couvrent la même date → supprimer l'un laisse le snapshot intact
    car l'autre import a encore une transaction sur cette date.

    Cas réel : import jan-mars puis import mars-juin, chevauchement en mars.
    Si on supprime le premier import, les transactions de mars du 2ème import
    existent encore → le snapshot mars doit rester.
    """
    shared_date = date(2026, 3, 15)

    log1 = _create_import_log(
        chf_account,
        user,
        date_min=date(2026, 3, 1),
        date_max=shared_date,
        file_seed="shared_1",
    )
    log2 = _create_import_log(
        chf_account,
        user,
        date_min=shared_date,
        date_max=date(2026, 4, 30),
        file_seed="shared_2",
    )

    _create_transaction(chf_account, log1, shared_date, "shared_t1")
    _create_transaction(
        chf_account, log2, shared_date, "shared_t2"
    )  # même date, import différent
    _create_snapshot(chf_account, shared_date)

    # Supprimer log1 — log2 a encore une transaction sur shared_date
    log1.delete()

    # Le snapshot doit survivre
    assert BalanceSnapshot.objects.filter(
        account=chf_account, date=shared_date
    ).exists()


@pytest.mark.django_db
def test_snapshot_deleted_when_last_covering_import_removed(chf_account, user):
    """
    Le snapshot est supprimé quand le DERNIER import couvrant cette date est supprimé.
    Complément du test précédent : cette fois on supprime les deux logs.
    """
    shared_date = date(2026, 3, 15)

    log1 = _create_import_log(
        chf_account,
        user,
        date_min=shared_date,
        date_max=shared_date,
        file_seed="last_1",
    )
    log2 = _create_import_log(
        chf_account,
        user,
        date_min=shared_date,
        date_max=shared_date,
        file_seed="last_2",
    )

    _create_transaction(chf_account, log1, shared_date, "last_t1")
    _create_transaction(chf_account, log2, shared_date, "last_t2")
    _create_snapshot(chf_account, shared_date)

    log1.delete()
    assert BalanceSnapshot.objects.filter(
        account=chf_account, date=shared_date
    ).exists()  # log2 still there

    log2.delete()
    assert not BalanceSnapshot.objects.filter(
        account=chf_account, date=shared_date
    ).exists()  # now gone


# =============================================================================
# D. Signal — no-op quand date_min/max sont None
# =============================================================================


@pytest.mark.django_db
def test_delete_import_log_with_no_date_range_does_not_crash(chf_account, user):
    """
    Un ImportLog avec 0 transactions (date_min=None, date_max=None) peut être
    supprimé sans erreur. Le signal doit sortir proprement sans requête DB.

    Cas réel : import d'un fichier déjà entièrement en DB (tout skippé) →
    ImportLog créé avec count_created=0, date_min=None.
    """
    log = _create_import_log(
        chf_account, user, date_min=None, date_max=None, file_seed="nodate"
    )
    log.delete()  # ne doit pas lever d'exception
    assert ImportLog.objects.count() == 0


# =============================================================================
# E. date_min / date_max peuplés après import
# =============================================================================


@pytest.mark.django_db
def test_import_service_sets_date_min_and_date_max(chf_account, user):
    """
    Après un import réussi, ImportLog.date_min et date_max reflètent
    la première et dernière date des transactions créées.
    """
    service = ImportService()
    transactions = [
        {**make_tx("d1"), "date": "2026-01-15"},
        {**make_tx("d2"), "date": "2026-02-20"},
        {**make_tx("d3"), "date": "2026-03-05"},
    ]

    result = service.run(
        transactions, chf_account, user, "file.csv", make_file_hash("dates")
    )

    log = ImportLog.objects.get(pk=result.log_pk)
    assert log.date_min == date(2026, 1, 15)
    assert log.date_max == date(2026, 3, 5)


@pytest.mark.django_db
def test_import_service_date_min_max_same_when_single_transaction(chf_account, user):
    """Import d'une seule transaction → date_min == date_max."""
    service = ImportService()
    transactions = [{**make_tx("single"), "date": "2026-06-01"}]

    result = service.run(
        transactions, chf_account, user, "file.csv", make_file_hash("single")
    )

    log = ImportLog.objects.get(pk=result.log_pk)
    assert log.date_min == log.date_max == date(2026, 6, 1)


# =============================================================================
# F. date_min / date_max restent None si 0 nouvelles transactions
# =============================================================================


@pytest.mark.django_db
def test_import_service_date_min_max_none_when_all_skipped(chf_account, user):
    """
    Si toutes les transactions sont des doublons (tout skippé), date_min et date_max
    restent None sur le log — il n'y a rien à dater.

    Cas réel : re-import d'une période déjà importée → utile pour "marquer comme synchronisé"
    sans polluer les méta-données de date du log.
    """
    service = ImportService()
    tx = make_tx("skip_dates")

    # Premier import : crée la transaction
    service.run([tx], chf_account, user, "file1.csv", make_file_hash("skip1"))

    # Deuxième import : même transaction, file_hash différent → tout skippé
    result = service.run([tx], chf_account, user, "file2.csv", make_file_hash("skip2"))

    log = ImportLog.objects.get(pk=result.log_pk)
    assert result.count_created == 0
    assert result.count_skipped == 1
    assert log.date_min is None
    assert log.date_max is None


# =============================================================================
# G. log_pk — ImportResult.log_pk pointe vers le bon ImportLog
# =============================================================================


@pytest.mark.django_db
def test_import_result_log_pk_matches_created_import_log(chf_account, user):
    """
    ImportResult.log_pk doit pointer vers l'ImportLog créé en DB.
    La vue import_confirm utilise ce PK pour stocker le fichier source.
    """
    service = ImportService()
    result = service.run(
        [make_tx("logpk")], chf_account, user, "file.csv", make_file_hash("logpk")
    )

    assert result.log_pk is not None
    assert ImportLog.objects.filter(pk=result.log_pk).exists()


@pytest.mark.django_db
def test_dry_run_does_not_set_log_pk(chf_account, user):
    """En dry_run, aucun ImportLog n'est créé → log_pk doit rester None."""
    service = ImportService()
    result = service.run(
        [make_tx("dry_logpk")],
        chf_account,
        user,
        "file.csv",
        make_file_hash("dry_logpk"),
        dry_run=True,
    )

    assert result.log_pk is None
    assert ImportLog.objects.count() == 0
