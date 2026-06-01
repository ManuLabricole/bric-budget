"""
transactions/management/commands/import_cic.py

CLI entry point for importing a CIC France Excel export.

CIC exports are multi-sheet: one sheet per account (C/C, Livret A, LDDS...).
This command loops over sheets and calls ImportService.run() once per account.

Responsibilities of this command (and only these):
    1. Validate the file exists and looks like a CIC Excel
    2. Discover account sheets in the file
    3. For each sheet: find the matching Account in DB (via contract_number)
    4. Call ImportService.run() per account — all DB logic lives there
    5. Print the result per account + a global summary

Usage:
    python manage.py import_cic --file path/to/export.xlsx          # dry-run (default)
    python manage.py import_cic --file path/to/export.xlsx --commit  # write to DB
    make import-cic FILE=path/to/export.xlsx
"""

import logging
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from connectors.cic.parser import CICConnector
from connectors.resolver import AccountMatch, detect_connector, resolve_accounts
from transactions.services import ImportResult, ImportService, compute_file_hash

logger = logging.getLogger(__name__)

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Import a CIC Excel export. Dry-run by default — add --commit to write to DB."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the CIC Excel export file (.xlsx)",
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
        if not isinstance(connector, CICConnector):
            raise CommandError(
                f"{filepath.name} does not look like a CIC Excel export.\n"
                "Expected an .xlsx file with a 'Vos comptes' sheet."
            )

        # ── 2. Get importing user ─────────────────────────────────────────────
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

        # ── 3. Discover account sheets via resolver ───────────────────────────
        # resolve_accounts() retourne 1 AccountMatch par feuille reconnue en DB.
        # Les feuilles sans compte configuré lèvent Account.DoesNotExist.
        try:
            matches = resolve_accounts(connector, filepath)
        except Exception as e:
            logger.exception("import_cic: resolve_accounts failed for %s", filepath)
            raise CommandError(str(e)) from e

        self.stdout.write(f"\nFile    : {filepath.name}")
        self.stdout.write(f"Sheets  : {len(matches)} account(s) found")
        self.stdout.write(
            f"Mode    : {'DRY RUN — no DB writes' if dry_run else 'COMMIT — writing to DB'}\n"
        )

        # file_hash is the same for all sheets — compute once
        file_hash = compute_file_hash(filepath)

        # ── 4. Process each sheet ─────────────────────────────────────────────
        total = ImportResult()

        # On a besoin du balance par sheet — on le récupère depuis get_account_sheets
        # (resolve_accounts ne le transmet pas pour rester simple).
        sheets_info = {
            s["sheet_name"]: s for s in connector.get_account_sheets(filepath)
        }

        for match in matches:
            sheet_info = sheets_info.get(match.sheet_name, {})
            self._process_sheet(
                filepath=filepath,
                match=match,
                balance=sheet_info.get("balance"),
                connector=connector,
                user=user,
                file_hash=file_hash,
                dry_run=dry_run,
                total=total,
            )

        # ── 5. Global summary ─────────────────────────────────────────────────
        self.stdout.write("=" * 50)
        self.stdout.write(self.style.SUCCESS("Global summary"))
        self.stdout.write(f"  Created : {total.count_created}")
        self.stdout.write(f"  Skipped : {total.count_skipped} (duplicates)")
        if total.count_errors:
            self.stdout.write(self.style.ERROR(f"  Errors  : {total.count_errors}"))
        else:
            self.stdout.write("  Errors  : 0")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry run — nothing written. Add --commit to import.\n"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nImport complete.\n"))

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _process_sheet(
        self,
        filepath: Path,
        match: AccountMatch,
        balance: float | None,
        connector: CICConnector,
        user,
        file_hash: str,
        dry_run: bool,
        total: ImportResult,
    ):
        """
        Process one account sheet: parse, call service, print.

        `match` vient du resolver — account déjà résolu, sheet_name et parse_kwargs inclus.
        `balance` vient de get_account_sheets() — extrait du footer de la feuille.
        `total` est muté en place pour le résumé global.
        """
        account = match.account
        sheet_name = match.sheet_name

        self.stdout.write(f"{'─' * 50}")
        self.stdout.write(f"Sheet   : {sheet_name}")
        self.stdout.write(f"Account : {account.name} (id={account.pk})")
        if balance is not None:
            self.stdout.write(f"Balance : {balance:,.2f} {account.currency}")

        # ── Parse this sheet ──────────────────────────────────────────────────
        transactions = connector.parse_sheet(filepath, sheet_name)  # type: ignore[arg-type]

        # ── Unique file_hash per (file, sheet) ────────────────────────────────
        # ImportLog.file_hash is unique=True and CharField(max_length=40).
        # A CIC file contains multiple sheets — if we used the same file_hash for
        # all sheets, the second sheet would be rejected as "already imported".
        # We hash the combination file_hash+sheet_name to produce a new 40-char SHA1.
        import hashlib

        sheet_file_hash = hashlib.sha1(  # nosemgrep
            f"{file_hash}:{sheet_name}".encode(), usedforsecurity=False
        ).hexdigest()

        # ── Call service ──────────────────────────────────────────────────────
        result = ImportService().run(
            transactions=transactions,
            account=account,
            imported_by=user,
            filename=f"{filepath.name} [{sheet_name}]",
            file_hash=sheet_file_hash,
            balance=balance,
            dry_run=dry_run,
        )

        # ── Per-sheet result ──────────────────────────────────────────────────
        self.stdout.write(f"  Created : {result.count_created}")
        self.stdout.write(f"  Skipped : {result.count_skipped} (duplicates)")
        if result.count_errors:
            self.stdout.write(self.style.ERROR(f"  Errors  : {result.count_errors}"))
            for msg in result.error_detail:
                self.stdout.write(self.style.ERROR(f"    {msg}"))

        self.stdout.write("")

        # Accumulate into global total
        total.count_created += result.count_created
        total.count_skipped += result.count_skipped
        total.count_errors += result.count_errors
        total.error_detail.extend(result.error_detail)
