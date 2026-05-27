"""
transactions/management/commands/import_yuh.py

CLI entry point for importing a Yuh CSV export.

Responsibilities of this command (and only these):
    1. Validate the file exists and looks like a Yuh CSV
    2. Find the matching Yuh account in the DB (bank-specific logic)
    3. Get the user who is running the import (for the audit log)
    4. Call ImportService.run() — all DB logic lives there
    5. Print the result

Everything else — deduplication, card resolution, categorisation,
BalanceSnapshot, ImportLog — is handled by ImportService.

Usage:
    python manage.py import_yuh --file path/to/export.csv          # dry-run (default)
    python manage.py import_yuh --file path/to/export.csv --commit  # write to DB
    make import-yuh FILE=path/to/export.csv
"""

import logging
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from connectors.resolver import detect_connector, resolve_accounts
from connectors.yuh.parser import YuhConnector
from transactions.services import ImportService, compute_file_hash

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import a Yuh CSV export. Dry-run by default — add --commit to write to DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the Yuh CSV export file",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            default=False,
            help="Write transactions to the database (default: dry-run only)",
        )

    def handle(self, *args, **options):
        filepath = Path(options["file"])
        dry_run = not options["commit"]

        # ── 1. File validation ────────────────────────────────────────────────
        if not filepath.exists():
            raise CommandError(f"File not found: {filepath}")

        connector = detect_connector(filepath)
        if not isinstance(connector, YuhConnector):
            raise CommandError(
                f"{filepath.name} does not look like a Yuh CSV export.\n"
                "Expected columns: DATE; ACTIVITY TYPE; ACTIVITY NAME; DEBIT; ..."
            )

        # ── 2. Find Yuh account ───────────────────────────────────────────────
        try:
            matches = resolve_accounts(connector, filepath)
        except Exception as e:
            logger.exception("import_yuh: resolve_accounts failed for %s", filepath)
            raise CommandError(str(e)) from e
        account = matches[0].account

        # ── 3. Get importing user ─────────────────────────────────────────────
        # DEV/CLI ONLY — management commands have no HTTP request, so no request.user.
        # We fall back to the first active superuser for the ImportLog audit trail.
        #
        # ⚠️ In production (Phase 6 web upload), the view passes request.user directly:
        #     ImportService().run(..., imported_by=request.user, ...)
        # The service doesn't care where the user comes from — that's the caller's job.
        user = User.objects.filter(is_superuser=True, is_active=True).first()
        if not user:
            raise CommandError(
                "No active superuser found. Run `make create-superuser` first."
            )

        # ── 4. Parse + call service ───────────────────────────────────────────
        self.stdout.write(f"\nFile    : {filepath.name}")
        self.stdout.write(f"Account : {account.name} (id={account.pk})")
        self.stdout.write(
            f"Mode    : {'DRY RUN — no DB writes' if dry_run else 'COMMIT — writing to DB'}\n"
        )

        transactions = connector.parse(filepath)
        balance = connector.extract_balance(filepath)
        file_hash = compute_file_hash(filepath)

        if balance is not None:
            self.stdout.write(f"Balance : {balance:,.2f} {account.currency}")

        result = ImportService().run(
            transactions=transactions,
            account=account,
            imported_by=user,
            filename=filepath.name,
            file_hash=file_hash,
            balance=balance,
            dry_run=dry_run,
        )

        # ── 5. Print result ───────────────────────────────────────────────────
        self._print_result(result, dry_run)

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _print_result(self, result, dry_run: bool):
        """Print a summary of the import result."""
        self.stdout.write(self.style.SUCCESS("\n--- Result ---"))
        self.stdout.write(f"  Created  : {result.count_created}")
        self.stdout.write(f"  Skipped  : {result.count_skipped} (duplicates)")

        if result.count_errors:
            self.stdout.write(self.style.ERROR(f"  Errors   : {result.count_errors}"))
            for msg in result.error_detail:
                self.stdout.write(self.style.ERROR(f"    {msg}"))
        else:
            self.stdout.write("  Errors   : 0")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry run — nothing written. Add --commit to import.\n"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nImport complete.\n"))
