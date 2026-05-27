"""
transactions/management/commands/import_all.py

Scans a directory of raw bank exports and runs the correct import command
for each recognized file. Unrecognized files are listed but skipped.

How it works
------------
Each connector implements `matches_file(filepath) -> bool`.
import_all tries every known connector in order on each file.
When a match is found, it calls the corresponding management command
via call_command() — all account-finding, ImportService, and logging
logic stays in the original command.

Connector → command mapping:
    YuhConnector  → import_yuh
    UBSConnector  → import_ubs
    CICConnector  → import_cic

Usage:
    python manage.py import_all                  # dry-run, default dir
    python manage.py import_all --commit         # write to DB
    python manage.py import_all --dir assets/private/data/raw --commit
    make import-all [COMMIT=1]
"""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand

from connectors.cic.parser import CICConnector
from connectors.resolver import detect_connector
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector

# Default directory to scan — relative to the project root (where make runs).
DEFAULT_RAW_DIR = Path("assets/private/data/raw")

# Mapping connecteur → nom de la commande de management.
# Synchronisé avec CONNECTORS dans connectors/resolver.py.
CONNECTOR_COMMAND = {
    YuhConnector: "import_yuh",
    UBSConnector: "import_ubs",
    CICConnector: "import_cic",
}


class Command(BaseCommand):
    help = (
        "Scan a directory of raw bank exports and import all recognized files. "
        "Dry-run by default — add --commit to write to DB."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=str(DEFAULT_RAW_DIR),
            help=f"Directory to scan (default: {DEFAULT_RAW_DIR})",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            default=False,
            help="Write transactions to the database (default: dry-run only)",
        )

    def handle(self, *args, **options):
        raw_dir = Path(options["dir"])
        dry_run = not options["commit"]

        # ── 1. Validate directory ─────────────────────────────────────────────
        if not raw_dir.exists():
            self.stderr.write(self.style.ERROR(f"Directory not found: {raw_dir}"))
            return

        # Collect all non-hidden files, sorted for deterministic output.
        all_files = sorted(
            f for f in raw_dir.iterdir() if f.is_file() and not f.name.startswith(".")
        )

        if not all_files:
            self.stdout.write(self.style.WARNING(f"No files found in {raw_dir}"))
            return

        # ── 2. Detect connector for each file ─────────────────────────────────
        # We separate detection from import so we can print the full plan upfront
        # before writing anything to the DB.
        matched = []  # list of (filepath, command_name)
        skipped = []  # files with no matching connector

        for filepath in all_files:
            connector = detect_connector(filepath)
            if connector is not None:
                command_name = CONNECTOR_COMMAND.get(type(connector))
                matched.append((filepath, command_name))
            else:
                skipped.append(filepath)

        # ── 3. Print the plan ─────────────────────────────────────────────────
        self.stdout.write(f"\nDirectory : {raw_dir}")
        self.stdout.write(
            f"Mode      : {'DRY RUN — no DB writes' if dry_run else 'COMMIT — writing to DB'}"
        )
        self.stdout.write(
            f"Files     : {len(matched)} recognized, {len(skipped)} skipped\n"
        )

        if skipped:
            self.stdout.write(self.style.WARNING("Skipped (no connector matched):"))
            for f in skipped:
                self.stdout.write(f"  {f.name}")
            self.stdout.write("")

        if not matched:
            self.stdout.write(self.style.WARNING("Nothing to import."))
            return

        # ── 4. Run each import ────────────────────────────────────────────────
        # call_command() reuses the full logic of each import command:
        # account finding, ImportService, BalanceSnapshot, ImportLog, result printing.
        # We only orchestrate — no DB logic here.
        for filepath, command_name in matched:
            self.stdout.write("=" * 60)
            self.stdout.write(f"→ {filepath.name}  [{command_name}]")
            self.stdout.write("=" * 60)
            call_command(
                command_name,  # type: ignore[arg-type]
                file=str(filepath),
                commit=options["commit"],
                stdout=self.stdout,
                stderr=self.stderr,
            )
