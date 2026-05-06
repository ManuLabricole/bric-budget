"""
tests/services/test_import_zero_tx.py — Tests du cas "0 nouvelles transactions".

Scénario : l'utilisateur upload un fichier bancaire dont toutes les transactions
sont déjà présentes en DB (hash déjà vu). Le dry-run retourne count_created=0
et count_skipped=N.

Comportements attendus :
    1. ImportService.run() crée quand même un ImportLog (count_created=0, status=SUCCESS)
    2. result.log_pk est non-None — le log a bien été créé
    3. Le statut est SUCCESS (aucune erreur, juste des doublons)
    4. count_skipped reflète le nombre de transactions ignorées

Pourquoi tester ça ?
    Sans ImportLog, le badge de sync du compte reste "stale" indéfiniment même si
    le compte est parfaitement à jour. La création du log est le signal que le
    compte a été synchronisé.

Pattern de test :
    1. Importer un fichier une première fois (crée les transactions en DB)
    2. Importer le même contenu avec un file_hash différent (simule un nouveau export)
    3. Vérifier que l'ImportLog est créé avec count_created=0
"""

from tests.services.conftest import make_file_hash, make_tx

# =============================================================================
# Tests du service ImportService
# =============================================================================


class TestImportServiceZeroNewTransactions:
    """Tests du comportement d'ImportService quand toutes les transactions existent."""

    def test_zero_new_tx_creates_import_log(self, db, chf_account, user):
        """
        Un import "all skipped" crée quand même un ImportLog.

        Scénario :
            - Import 1 : insérer 2 transactions avec file_hash="file_a"
            - Import 2 : mêmes 2 transactions, file_hash="file_b" (nouveau fichier)
            - Vérifier que l'Import 2 crée un ImportLog avec count_created=0
        """
        from transactions.models import ImportLog
        from transactions.services import ImportService

        service = ImportService()
        tx1 = make_tx("zero_a")
        tx2 = make_tx("zero_b")

        # ── Import 1 : insérer les transactions ──────────────────────────────
        service.run(
            transactions=[tx1, tx2],
            account=chf_account,
            imported_by=user,
            filename="original.csv",
            file_hash=make_file_hash("zero_file_1"),
            dry_run=False,
        )
        assert ImportLog.objects.count() == 1

        # ── Import 2 : même transactions, nouveau file_hash ──────────────────
        result = service.run(
            transactions=[tx1, tx2],
            account=chf_account,
            imported_by=user,
            filename="same_content_new_export.csv",
            file_hash=make_file_hash("zero_file_2"),
            dry_run=False,
        )

        # Un second ImportLog doit exister
        assert ImportLog.objects.count() == 2
        assert result.count_created == 0
        assert result.count_skipped == 2

    def test_zero_new_tx_log_status_is_success(self, db, chf_account, user):
        """L'ImportLog créé pour un import "all skipped" a le statut SUCCESS."""
        from transactions.models import ImportLog
        from transactions.services import ImportService

        service = ImportService()
        tx = make_tx("status_a")

        # Import 1
        service.run(
            transactions=[tx],
            account=chf_account,
            imported_by=user,
            filename="first.csv",
            file_hash=make_file_hash("status_file_1"),
            dry_run=False,
        )

        # Import 2 — all skipped
        service.run(
            transactions=[tx],
            account=chf_account,
            imported_by=user,
            filename="second.csv",
            file_hash=make_file_hash("status_file_2"),
            dry_run=False,
        )

        second_log = ImportLog.objects.order_by("-imported_at").first()
        assert second_log.status == ImportLog.Status.SUCCESS
        assert second_log.count_created == 0
        assert second_log.count_errors == 0

    def test_zero_new_tx_log_pk_set_on_result(self, db, chf_account, user):
        """result.log_pk est non-None quand un ImportLog est créé (y compris 0 tx)."""
        from transactions.models import ImportLog
        from transactions.services import ImportService

        service = ImportService()
        tx = make_tx("pk_a")

        # Import 1
        service.run(
            transactions=[tx],
            account=chf_account,
            imported_by=user,
            filename="first.csv",
            file_hash=make_file_hash("pk_file_1"),
            dry_run=False,
        )

        # Import 2 — all skipped
        result = service.run(
            transactions=[tx],
            account=chf_account,
            imported_by=user,
            filename="second.csv",
            file_hash=make_file_hash("pk_file_2"),
            dry_run=False,
        )

        assert result.log_pk is not None
        # Le PK doit correspondre à un vrai ImportLog en DB
        assert ImportLog.objects.filter(pk=result.log_pk).exists()

    def test_dry_run_does_not_create_log(self, db, chf_account, user):
        """dry_run=True ne crée jamais d'ImportLog, et log_pk reste None."""
        from transactions.models import ImportLog
        from transactions.services import ImportService

        service = ImportService()

        result = service.run(
            transactions=[make_tx("dry_a"), make_tx("dry_b")],
            account=chf_account,
            imported_by=user,
            filename="preview.csv",
            file_hash=make_file_hash("dry_file"),
            dry_run=True,
        )

        assert ImportLog.objects.count() == 0
        assert result.log_pk is None
        assert result.count_created == 2  # aurait créé 2 si pas dry_run


# =============================================================================
# Test du champ log_pk sur ImportResult (cas normal)
# =============================================================================


class TestImportResultLogPk:
    """Tests du champ log_pk ajouté à ImportResult."""

    def test_run_sets_log_pk_after_commit(self, db, chf_account, user):
        """result.log_pk correspond au PK de l'ImportLog créé en DB."""
        from transactions.models import ImportLog
        from transactions.services import ImportService

        service = ImportService()
        result = service.run(
            transactions=[make_tx("logpk_a"), make_tx("logpk_b")],
            account=chf_account,
            imported_by=user,
            filename="test.csv",
            file_hash=make_file_hash("logpk_file"),
            dry_run=False,
        )

        assert result.log_pk is not None
        log = ImportLog.objects.get(pk=result.log_pk)
        assert log.count_created == 2
        assert log.account == chf_account
