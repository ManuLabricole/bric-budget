"""
transactions/management/commands/import_ubs.py

CLI entry point for importing a UBS CSV export.

Responsibilities of this command (and only these):
    1. Validate the file exists and looks like a UBS CSV
    2. Extract the IBAN from the file and find the matching account in DB
    3. Get the user who is running the import (for the audit log)
    4. Call ImportService.run() — all DB logic lives there
    5. Print the result

Usage:
    python manage.py import_ubs --file path/to/export.csv          # dry-run (default)
    python manage.py import_ubs --file path/to/export.csv --commit  # write to DB
    make import-ubs FILE=path/to/export.csv
"""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account
from connectors.ubs.parser import UBSConnector
from transactions.services import ImportService, compute_file_hash

User = get_user_model()


class Command(BaseCommand):
    help = "Import a UBS CSV export. Dry-run by default — add --commit to write to DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the UBS CSV export file",
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

        connector = UBSConnector()
        if not connector.matches_file(filepath):
            raise CommandError(
                f"{filepath.name} does not look like a UBS CSV export.\n"
                "Expected: IBAN on line 2, then standard UBS column headers."
            )

        # ── 2. Find UBS account via IBAN ──────────────────────────────────────
        # UBS embeds the IBAN in line 2 — this is how we identify which account
        # the file belongs to. Bank-specific logic: stays in this command.
        account = self._find_account(connector, filepath)

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

    def _find_account(self, connector: UBSConnector, filepath: Path):
        """
        Extract the account identifier from the file and find the matching Account in DB.

        UBSConnector.extract_account_identifier() returns the IBAN normalized (no spaces).
        We look it up directly via Account.contract_number — the universal import key.

        Same pattern used by all connectors that embed an identifier in their file.
        For sources without an identifier (Yuh), the command uses a convention fallback instead.
        """
        identifier = connector.extract_account_identifier(filepath)
        if not identifier:
            raise CommandError(
                "Could not extract account identifier (IBAN) from file (expected on line 2).\n"
                "The file may be corrupted or not a standard UBS export."
            )

        account = Account.objects.filter(
            contract_number=identifier,
            is_active=True,
        ).first()

        if account is None:
            raise CommandError(
                f"No account with contract_number='{identifier}' found in the database.\n"
                "Run `make seed` first, or set Account.contract_number to this value in the admin."
            )

        return account

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
