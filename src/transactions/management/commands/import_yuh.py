"""
transactions/management/commands/import_yuh.py

Parses a Yuh CSV export and prints a full import report.
Does NOT write anything to the database — report only at this stage.

What this command does:
    1. Detect that the file is a valid Yuh CSV (column signature check)
    2. Find the matching Yuh account in the database
    3. Load registered cards for this account (last_four → cardholder)
    4. Parse all transactions from the file
    5. Check each transaction's import_hash against existing DB transactions
    6. Print a full report: new / duplicate, with card/cardholder attribution

Usage:
    python manage.py import_yuh --file path/to/export.csv
    make import-yuh FILE=path/to/export.csv
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account, Card
from connectors.yuh.parser import YuhConnector
from transactions.models import Transaction


class Command(BaseCommand):
    help = "Parse a Yuh CSV export and print an import report (dry run — no DB writes)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the Yuh CSV export file",
        )

    def handle(self, *args, **options):
        filepath = Path(options["file"])

        # ── 1. File exists ────────────────────────────────────────────────
        if not filepath.exists():
            raise CommandError(f"File not found: {filepath}")

        # ── 2. Detect format ──────────────────────────────────────────────
        connector = YuhConnector()

        if not connector.matches_file(filepath):
            raise CommandError(
                f"{filepath.name} does not look like a Yuh CSV export.\n"
                "Expected columns: DATE; ACTIVITY TYPE; ACTIVITY NAME; DEBIT; ..."
            )

        self.stdout.write(self.style.SUCCESS("\n=== Yuh Import Report ==="))
        self.stdout.write(f"File    : {filepath.name}")

        # ── 3. Detect account ─────────────────────────────────────────────
        # Yuh files have no IBAN — we find the account by bank slug + type.
        # Error if 0 accounts (not seeded) or 2+ accounts (ambiguous).
        yuh_accounts = Account.objects.filter(
            bank__slug="yuh",
            account_type=Account.AccountType.CHECKING,
            is_active=True,
        )

        if yuh_accounts.count() == 0:
            raise CommandError(
                "No active Yuh checking account found in the database.\n"
                "Run `make seed` first, or create the account in the admin."
            )
        if yuh_accounts.count() > 1:
            raise CommandError(
                f"Multiple Yuh checking accounts found ({yuh_accounts.count()}).\n"
                "Cannot auto-assign. Please specify the account manually (not yet supported)."
            )

        account = yuh_accounts.first()
        self.stdout.write(f"Account : {account.name} (id={account.pk})")

        # ── 4. Load known cards for this account ──────────────────────────
        # Build {last_four: Card} so we can match each card transaction to
        # a cardholder in O(1) — one DB query total, no per-row queries.
        cards_by_last_four = {
            card.last_four: card
            for card in Card.objects.filter(
                checking_account__account=account,
                is_active=True,
            ).select_related("user")
        }

        if cards_by_last_four:
            card_summary = ", ".join(
                f"*{lf} ({c.user.first_name or c.user.email.split('@')[0]})"
                for lf, c in cards_by_last_four.items()
            )
            self.stdout.write(f"Cards   : {card_summary}")
        else:
            self.stdout.write("Cards   : none registered (run make seed)")

        # ── 5. Balance from filename ──────────────────────────────────────
        balance = connector.extract_balance(filepath)
        if balance is not None:
            self.stdout.write(f"Balance : {balance:,.2f} {account.currency}")
        else:
            self.stdout.write("Balance : not found in filename")

        # ── 6. Parse transactions ─────────────────────────────────────────
        self.stdout.write("")
        transactions = connector.parse(filepath)

        # ── 7. Deduplication check ────────────────────────────────────────
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

        # ── 8. Report ─────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("\n--- Summary ---"))
        self.stdout.write(f"  Total parsed  : {len(transactions)}")
        self.stdout.write(self.style.SUCCESS(f"  New           : {len(new_txs)}"))
        if duplicate_txs:
            self.stdout.write(
                self.style.WARNING(f"  Duplicates    : {len(duplicate_txs)}")
            )
        else:
            self.stdout.write("  Duplicates    : 0")

        # Helper: resolve last_four → "Prénom" or "unknown *XXXX"
        def card_label(last_four):
            if not last_four:
                return ""
            card = cards_by_last_four.get(last_four)
            if card:
                name = card.user.first_name or card.user.email.split("@")[0]
                return f" [{name} *{last_four}]"
            return f" [? *{last_four}]"  # card in file but not in DB

        # New transactions detail
        if new_txs:
            self.stdout.write(
                self.style.SUCCESS(f"\n--- New transactions ({len(new_txs)}) ---")
            )
            for tx in new_txs:
                sign = "+" if tx["amount"] > 0 else ""
                self.stdout.write(
                    f"  {tx['date']}  {sign}{tx['amount']:>10.2f} {tx['currency']}"
                    f"  {tx['merchant_name'][:35]:<35}{card_label(tx['card_last_four'])}"
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
                self.stdout.write(
                    f"  {tx['date']}  {sign}{tx['amount']:>10.2f} {tx['currency']}"
                    f"  {tx['merchant_name'][:35]:<35}{card_label(tx['card_last_four'])}  [DUPLICATE]"
                )

        self.stdout.write(self.style.SUCCESS("\n=== End of report ==="))
        self.stdout.write(
            "No data was written to the database. "
            "DB import will be added in the next step.\n"
        )
