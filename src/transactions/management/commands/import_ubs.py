"""
transactions/management/commands/import_ubs.py

Parses a UBS CSV export and prints a full import report.
Does NOT write anything to the database — report only at this stage.

What this command does:
    1. Detect that the file is a valid UBS CSV (IBAN line + column signature check)
    2. Extract the IBAN from the file — query the matching CheckingAccount in DB
    3. Parse all transactions from the file
    4. Check each transaction's import_hash against existing DB transactions
    5. Print a full report: new / duplicate / skipped

Usage:
    python manage.py import_ubs --file path/to/export.csv
    make import-ubs FILE=path/to/export.csv
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import CheckingAccount
from connectors.ubs.parser import UBSConnector
from transactions.models import Transaction


class Command(BaseCommand):
    help = "Parse a UBS CSV export and print an import report (dry run — no DB writes)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the UBS CSV export file",
        )

    def handle(self, *args, **options):
        filepath = Path(options["file"])

        # ── 1. File exists ────────────────────────────────────────────────
        if not filepath.exists():
            raise CommandError(f"File not found: {filepath}")

        # ── 2. Detect format ──────────────────────────────────────────────
        connector = UBSConnector()

        if not connector.matches_file(filepath):
            raise CommandError(
                f"{filepath.name} does not look like a UBS CSV export.\n"
                "Expected: IBAN on line 2, then standard UBS column headers."
            )

        self.stdout.write(self.style.SUCCESS("\n=== UBS Import Report ==="))
        self.stdout.write(f"File : {filepath.name}")

        # ── 3. Extract IBAN + detect account ─────────────────────────────
        # UBS files embed the IBAN in line 2 — this is how we identify the account.
        # We normalise the IBAN (strip spaces) before the DB lookup because the DB
        # may store it with or without spaces depending on how it was entered.
        raw_iban = connector.extract_iban(filepath)
        if not raw_iban:
            raise CommandError(
                "Could not extract IBAN from file (expected on line 2).\n"
                "The file may be corrupted or not a standard UBS export."
            )

        # Normalise: "CH9X XXXX XXXX XXXX XXXX X" → "CH9400243243693382 40P"
        # Actually we strip ALL spaces for the lookup — the DB value may or may
        # not contain spaces depending on how it was entered in the seed/admin.
        iban_normalised = raw_iban.replace(" ", "")
        self.stdout.write(f"IBAN  : {raw_iban}")

        # Query by normalised IBAN — we normalise both sides of the comparison.
        # Django doesn't have a built-in "strip spaces" lookup, so we fetch
        # CheckingAccounts for the UBS bank and compare normalised values in Python.
        # With at most a handful of accounts, this is fine.
        ubs_checking = CheckingAccount.objects.filter(account__bank__slug="ubs")

        account = None
        for ca in ubs_checking:
            if ca.iban.replace(" ", "") == iban_normalised:
                account = ca.account
                break

        if account is None:
            raise CommandError(
                f"No UBS checking account with IBAN {raw_iban} found in the database.\n"
                "Run `make seed` first, or add the account in the admin with this IBAN."
            )

        self.stdout.write(f"Account : {account.name} (id={account.pk})")

        # ── 4. Balance from metadata block ────────────────────────────────
        balance = connector.extract_balance(filepath)
        if balance is not None:
            self.stdout.write(f"Balance : {balance:,.2f} {account.currency}")
        else:
            self.stdout.write("Balance : not found in file")

        # ── 5. Parse transactions ─────────────────────────────────────────
        self.stdout.write("")
        transactions = connector.parse(filepath)

        # ── 6. Deduplication check ────────────────────────────────────────
        # Fetch all existing import_hashes for this account in one DB query.
        existing_hashes = set(
            Transaction.objects.filter(account=account).values_list(
                "import_hash", flat=True
            )
        )

        new_txs = []
        duplicate_txs = []

        for tx in transactions:
            if tx["import_hash"] in existing_hashes:
                duplicate_txs.append(tx)
            else:
                new_txs.append(tx)

        # ── 7. Report ─────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("\n--- Summary ---"))
        self.stdout.write(f"  Total parsed  : {len(transactions)}")
        self.stdout.write(self.style.SUCCESS(f"  New           : {len(new_txs)}"))
        if duplicate_txs:
            self.stdout.write(
                self.style.WARNING(f"  Duplicates    : {len(duplicate_txs)}")
            )
        else:
            self.stdout.write("  Duplicates    : 0")

        # New transactions detail — include time column when available
        if new_txs:
            self.stdout.write(
                self.style.SUCCESS(f"\n--- New transactions ({len(new_txs)}) ---")
            )
            for tx in new_txs:
                sign = "+" if tx["amount"] > 0 else ""
                # Show time if available, pad with spaces otherwise for alignment
                time_col = tx["time"] if tx["time"] else "        "
                self.stdout.write(
                    f"  {tx['date']}  {time_col}  {sign}{tx['amount']:>10.2f} {tx['currency']}"
                    f"  {tx['merchant_name'][:40]:<40}"
                )

        # Duplicate transactions detail
        if duplicate_txs:
            self.stdout.write(
                self.style.WARNING(
                    f"\n--- Duplicate transactions ({len(duplicate_txs)}) ---"
                )
            )
            for tx in duplicate_txs:
                sign = "+" if tx["amount"] > 0 else ""
                time_col = tx["time"] if tx["time"] else "        "
                self.stdout.write(
                    f"  {tx['date']}  {time_col}  {sign}{tx['amount']:>10.2f} {tx['currency']}"
                    f"  {tx['merchant_name'][:40]:<40}  [DUPLICATE]"
                )

        self.stdout.write(self.style.SUCCESS("\n=== End of report ==="))
        self.stdout.write(
            "No data was written to the database. "
            "DB import will be added in the next step.\n"
        )
