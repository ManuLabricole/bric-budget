"""
transactions/management/commands/import_cic.py

Parses a CIC France Excel export and prints a full import report.
Does NOT write anything to the database — report only at this stage.

The CIC Excel file contains multiple sheets — one per account:
  - C/C Contrat Personnel Global   → CheckingAccount (matched via IBAN/RIB)
  - Livret A                       → SavingsAccount  (matched via account_reference)
  - Livret de Développement Durable → SavingsAccount  (matched via account_reference)

What this command does for each sheet:
    1. Detect that the file is a valid CIC Excel (presence of "Vos comptes" sheet)
    2. List all account sheets + their RIB
    3. For each sheet: find the matching Account in DB, parse transactions,
       check import_hash vs DB, print report

Usage:
    python manage.py import_cic --file path/to/export.xlsx
    make import-cic FILE=path/to/export.xlsx
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Card
from connectors.cic.parser import CICConnector
from transactions.models import Transaction


class Command(BaseCommand):
    help = (
        "Parse a CIC Excel export and print an import report (dry run — no DB writes)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the CIC Excel export file (.xlsx)",
        )

    def handle(self, *args, **options):
        filepath = Path(options["file"])

        # ── 1. File exists ────────────────────────────────────────────────
        if not filepath.exists():
            raise CommandError(f"File not found: {filepath}")

        # ── 2. Detect format ──────────────────────────────────────────────
        connector = CICConnector()

        if not connector.matches_file(filepath):
            raise CommandError(
                f"{filepath.name} does not look like a CIC Excel export.\n"
                "Expected an .xlsx file with a 'Vos comptes' sheet."
            )

        self.stdout.write(self.style.SUCCESS("\n=== CIC Import Report ==="))
        self.stdout.write(f"File : {filepath.name}")

        # ── 3. Discover account sheets ────────────────────────────────────
        sheets = connector.get_account_sheets(filepath)
        self.stdout.write(f"Sheets found : {len(sheets)}")
        self.stdout.write("")

        # ── 4. Process each sheet ─────────────────────────────────────────
        for sheet_info in sheets:
            self._process_sheet(filepath, sheet_info, connector)

        self.stdout.write(self.style.SUCCESS("\n=== End of report ==="))
        self.stdout.write(
            "No data was written to the database. "
            "DB import will be added in the next step.\n"
        )

    def _process_sheet(self, filepath: Path, sheet_info: dict, connector: CICConnector):
        """
        Handle one account sheet: find DB account, parse, dedup, report.
        """
        sheet_name = sheet_info["sheet_name"]
        rib = sheet_info["rib"]  # normalised (no spaces)
        rib_raw = sheet_info["rib_raw"]  # with spaces (for display)
        balance = sheet_info["balance"]
        account_type_hint = sheet_info["account_type_hint"]

        self.stdout.write(f"{'─' * 60}")
        self.stdout.write(f"Sheet   : {sheet_name}")
        self.stdout.write(f"RIB     : {rib_raw}")
        self.stdout.write(f"Type    : {account_type_hint}")
        if balance is not None:
            self.stdout.write(f"Balance : {balance:,.2f} EUR")

        # ── Find matching Account in DB ───────────────────────────────────
        account = self._find_account(rib, account_type_hint)

        if account is None:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ No matching account found for RIB {rib_raw}\n"
                    f"  Update {'CheckingAccount.iban' if account_type_hint == 'checking' else 'SavingsAccount.account_reference'} "
                    f"in the admin with this RIB (without spaces: {rib})"
                )
            )
            self.stdout.write("")
            return

        self.stdout.write(f"Account : {account.name} (id={account.pk})")

        # ── Load known cards for this account (checking only) ─────────────
        cards_by_last_four = {}
        if account_type_hint == "checking":
            try:
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
            except Exception:
                pass  # savings accounts have no CheckingAccount

        # ── Parse transactions ────────────────────────────────────────────
        self.stdout.write("")
        transactions = connector.parse_sheet(filepath, sheet_name)

        # ── Deduplication check ───────────────────────────────────────────
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

        # ── Summary ───────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("--- Summary ---"))
        self.stdout.write(f"  Total parsed  : {len(transactions)}")
        self.stdout.write(self.style.SUCCESS(f"  New           : {len(new_txs)}"))
        if duplicate_txs:
            self.stdout.write(
                self.style.WARNING(f"  Duplicates    : {len(duplicate_txs)}")
            )
        else:
            self.stdout.write("  Duplicates    : 0")

        # Helper: card label for a transaction
        def card_label(last_four):
            if not last_four:
                return ""
            card = cards_by_last_four.get(last_four)
            if card:
                name = card.user.first_name or card.user.email.split("@")[0]
                return f" [{name} *{last_four}]"
            return f" [? *{last_four}]"

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

        # Duplicates detail
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

        self.stdout.write("")

    def _find_account(self, rib_normalised: str, account_type_hint: str):
        """
        Find the Account in DB matching this contract number (RIB normalised).

        CIC identifies accounts by a contract number ("numéro de contrat"),
        which is their RIB without spaces: "100961802700064764601".
        We store this in Account.contract_number and match directly — no need
        to look at CheckingAccount.iban or SavingsAccount.account_reference.

        account_type_hint is kept for logging context in _process_sheet(),
        but is not used for the DB lookup itself.

        Returns None if no match found.
        """
        from accounts.models import Account

        return Account.objects.filter(
            bank__slug="cic",
            is_active=True,
            contract_number=rib_normalised,
        ).first()
