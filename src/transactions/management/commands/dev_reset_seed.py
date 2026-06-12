"""
transactions/management/commands/dev_reset_seed.py

⛔ DEV ONLY — Wipes all business data (referentials + personal accounts/cards).

Refuses to run when DEBUG=False (production).
Pass --force-prod to override (rarely needed).

Re-populate after a reset:
    make seed              → referentials (categories + institutions)
    python manage.py setup_accounts   → personal accounts (CSV/XLSX exports)

Why a separate command (not Django's `flush`)?
----------------------------------------------
`manage.py flush` wipes EVERY table including Django internals (sessions,
content types, permissions, the superuser). That means re-running
create_user + re-creating permissions from scratch.

This command only deletes the business data seeded by seed_initial:
    - Cards
    - CheckingAccounts + SavingsAccounts
    - Accounts
    - Banks
    - SubCategories
    - Categories
    - Carys user (carys@home.local)

The superuser (Emmanuel) and all Django system tables are left untouched.

Deletion order matters:
    FK constraints require deleting children before parents.
    Cards → CheckingAccounts/SavingsAccounts → Accounts → Banks
    SubCategories → Categories

Usage:
    python manage.py dev_reset_seed
    make reset-seed
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Account, Card, CheckingAccount, Institution, SavingsAccount
from transactions.management._dev_guard import (
    add_force_prod_argument,
    assert_dev_environment,
)
from transactions.models import Category, ImportLog, SubCategory, Transaction


class Command(BaseCommand):
    help = (
        "[DEV ONLY] Deletes all data created by seed_initial "
        "(keeps superuser and Django internals)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt",
        )
        add_force_prod_argument(parser)

    def handle(self, *args, **options):
        # Guard : refuse de tourner en prod (DEBUG=False) sauf --force-prod
        if not options.get("force_prod"):
            assert_dev_environment("dev_reset_seed")

        # Safety confirmation — destructive operation
        # --yes flag allows scripting (e.g. make reset-seed in CI)
        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    "This will delete ALL seeded data (banks, accounts, cards, categories)."
                )
            )
            confirm = input("Type 'yes' to confirm: ")
            if confirm != "yes":
                self.stdout.write("Aborted.")
                return

        self.stdout.write(self.style.WARNING("=== dev_reset_seed ==="))

        # ── Transactions + ImportLogs (FK to Account — PROTECTED) ────────
        # Transaction.account and ImportLog.account use on_delete=PROTECT,
        # so they must be deleted before Account.
        count = Transaction.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  Transactions deleted:    {count}"))

        count = ImportLog.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  ImportLogs deleted:      {count}"))

        # ── Cards (FK to CheckingAccount + User) ──────────────────────────
        # Must be deleted before CheckingAccount
        count = Card.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  Cards deleted:           {count}"))

        # ── CheckingAccounts + SavingsAccounts ────────────────────────────
        # CASCADE from Account.delete() would handle these, but being explicit
        # is more readable and avoids surprises if on_delete ever changes.
        count = CheckingAccount.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  CheckingAccounts deleted: {count}"))

        count = SavingsAccount.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  SavingsAccounts deleted:  {count}"))

        # ── Accounts ──────────────────────────────────────────────────────
        count = Account.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  Accounts deleted:        {count}"))

        # ── Banks ─────────────────────────────────────────────────────────
        count = Institution.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  Banks deleted:           {count}"))

        # ── SubCategories (FK to Category) ────────────────────────────────
        count = SubCategory.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  SubCategories deleted:   {count}"))

        # ── Categories ────────────────────────────────────────────────────
        count = Category.objects.all().delete()[0]
        self.stdout.write(self.style.SUCCESS(f"  Categories deleted:      {count}"))

        # ── Carys user ────────────────────────────────────────────────────
        # We only delete carys@home.local — never the superuser
        User = get_user_model()
        carys_count, _ = User.objects.filter(email="carys@home.local").delete()
        self.stdout.write(
            self.style.SUCCESS(f"  Carys user deleted:      {carys_count}")
        )

        self.stdout.write(
            self.style.WARNING(
                "=== dev_reset_seed complete — run `make seed` to re-populate ==="
            )
        )
