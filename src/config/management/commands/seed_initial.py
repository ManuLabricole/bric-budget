"""
config/management/commands/seed_initial.py

Populates the database with reference data needed before any CSV import.

Why a seed command?
-------------------
Django's `loaddata` works with fixtures (JSON/YAML) but is hard to maintain
when data has relationships (bank → account → card) and conditional logic.
A Python command is readable, debuggable, and easy to update.

What this command creates (in order):
    1. Categories + SubCategories — from categories.json (Finary taxonomy)
    2. Banks                      — Yuh, UBS, CIC, Boursorama
    3. Accounts                   — 7 accounts (CheckingAccount or SavingsAccount)
    4. Carys user                 — minimal secondary user for card assignment
    5. Cards                      — 4 cards (2 on UBS: Emmanuel + Carys)

Idempotency + updates:
    Every object uses update_or_create() — running the command twice is safe
    AND propagates any changes made in this file to the database.
    This means the seed file IS the source of truth.

    get_or_create  → creates if absent, returns unchanged if exists (no sync)
    update_or_create → creates if absent, UPDATES defaults if exists (sync)

Prerequisites:
    `make create-superuser` must have been run before this command.
    The admin user (SUPERUSER_EMAIL in .env) is used for Emmanuel's cards.

Usage:
    python manage.py seed_initial
    make seed
"""

import json
from pathlib import Path

from decouple import config
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Account, Bank, Card, CheckingAccount, SavingsAccount
from transactions.models import Category, SubCategory


class Command(BaseCommand):
    help = "Seeds the database with initial reference data (banks, accounts, cards, categories)"

    def handle(self, *args, **options):
        """
        Runs all seed steps in dependency order:
        Categories must exist before SubCategories.
        Banks must exist before Accounts.
        Accounts must exist before Cards.
        """
        self.stdout.write(self.style.SUCCESS("=== BricBudget seed_initial ==="))

        self._seed_categories()
        banks = self._seed_banks()
        accounts = self._seed_accounts(banks)
        self._seed_cards(accounts)

        self.stdout.write(self.style.SUCCESS("=== Seed complete ==="))

    # =========================================================================
    # Step 1 — Categories + SubCategories
    # =========================================================================

    def _seed_categories(self):
        """
        Reads categories.json and creates/updates Category + SubCategory objects.

        Path resolution:
            settings.BASE_DIR = src/
            BASE_DIR.parent   = project root (BudgetTracker/)
            → BudgetTracker/assets/private/references/categories/categories.json

        Lookup key: slug (unique in DB).
        default_nature="neutral" in JSON → stored as "" (blank) in DB.
        """
        json_path = (
            Path(settings.BASE_DIR).parent
            / "assets"
            / "private"
            / "references"
            / "categories"
            / "categories.json"
        )

        if not json_path.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"categories.json not found at {json_path} — skipping categories"
                )
            )
            return

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        cat_created = 0
        cat_updated = 0
        sub_created = 0
        sub_updated = 0

        for cat_data in data["categories"]:
            # update_or_create: lookup by slug, set/update all other fields.
            # If the category already exists, its fields are updated to match the JSON.
            # `created` is True on first run, False on subsequent runs (updated).
            category, created = Category.objects.update_or_create(
                slug=cat_data["slug"],
                defaults={
                    "name": cat_data["name"],
                    "icon": cat_data.get("icon", ""),
                    "colour_hex": cat_data.get("colour_hex", ""),
                    "order": cat_data.get("order", 0),
                    "is_system": cat_data.get("is_system", False),
                    "is_active": cat_data.get("is_active", True),
                },
            )

            if created:
                cat_created += 1
            else:
                cat_updated += 1

            for sub_data in cat_data.get("subcategories", []):
                # "neutral" in JSON means no budget nature → maps to "" (blank) in DB
                nature = sub_data.get("default_nature", "")
                if nature == "neutral":
                    nature = ""

                _, sub_c = SubCategory.objects.update_or_create(
                    slug=sub_data["slug"],
                    defaults={
                        "category": category,
                        "name": sub_data["name"],
                        "icon": sub_data.get("icon", ""),
                        "default_nature": nature,
                        "is_active": sub_data.get("is_active", True),
                    },
                )

                if sub_c:
                    sub_created += 1
                else:
                    sub_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Categories:    {cat_created} created, {cat_updated} updated"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  SubCategories: {sub_created} created, {sub_updated} updated"
            )
        )

    # =========================================================================
    # Step 2 — Banks
    # =========================================================================

    def _seed_banks(self):
        """
        Creates/updates the 4 banks.

        icon_slug maps to static/icons/banks/miniature/<icon_slug>.[svg|png].
        Boursorama icon is not yet in static/ — it will display no icon until
        the file static/icons/banks/miniature/boursorama.* is added.

        Returns a dict of {slug: Bank instance} for use in _seed_accounts().
        """

        # Each tuple: (name, slug, country, currency, icon_slug)
        banks_data = [
            ("Yuh", "yuh", "CH", "CHF", "yuh"),
            ("UBS", "ubs", "CH", "CHF", "ubs"),
            ("CIC", "cic", "FR", "EUR", "cic"),
            ("Boursorama", "boursorama", "FR", "EUR", "boursorama"),
        ]

        created_count = 0
        updated_count = 0
        banks = {}

        for name, slug, country, currency, icon_slug in banks_data:
            bank, created = Bank.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "country": country,
                    "default_currency": currency,
                    "icon_slug": icon_slug,
                    "is_active": True,
                },
            )
            banks[slug] = bank

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Banks:         {created_count} created, {updated_count} updated"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "  ⚠ Boursorama: icon missing at static/icons/banks/miniature/boursorama.* "
                "— download it from brandfetch.com"
            )
        )

        return banks

    # =========================================================================
    # Step 3 — Accounts (Account + CheckingAccount or SavingsAccount)
    # =========================================================================

    def _seed_accounts(self, banks):
        """
        Creates/updates Account records and their specialised sub-type.

        Why two objects per account?
        ----------------------------
        Account holds the common fields (bank, name, type, currency).
        CheckingAccount / SavingsAccount hold the type-specific fields
        (IBAN/BIC for checking, interest_rate for savings).
        This is the OneToOne pattern decided in Phase 0A — no Django multi-table
        inheritance, full control over the SQL joins.

        Lookup key: (bank, name) — the natural unique key for an account.

        IBANs are intentionally fake — format is plausible but not valid.
        They are placeholders for the real values the user will update manually.

        Returns a dict of {key: Account} for card assignment in _seed_cards().
        """

        accounts_data = [
            # ── Yuh ──────────────────────────────────────────────────────────
            {
                "key": "yuh_cc",
                "bank_slug": "yuh",
                "name": "Yuh C/C",
                "account_type": Account.AccountType.CURRENT,
                "currency": "CHF",
                "subtype": "checking",
                "iban": "CH00 0000 0000 0000 0000 Y",
                "bic": "YUHHCHZZ",
            },
            # ── UBS ──────────────────────────────────────────────────────────
            {
                "key": "ubs_cc",
                "bank_slug": "ubs",
                "name": "UBS C/C",
                "account_type": Account.AccountType.CURRENT,
                "currency": "CHF",
                "subtype": "checking",
                "iban": "CH00 0000 0000 0000 0000 U",
                "bic": "UBSWCHZH",
            },
            {
                "key": "ubs_epargne",
                "bank_slug": "ubs",
                "name": "UBS Épargne",
                "account_type": Account.AccountType.SAVINGS,
                "currency": "CHF",
                "subtype": "savings",
                "interest_rate": "0.25",
                "account_reference": "",
            },
            # ── CIC ──────────────────────────────────────────────────────────
            {
                "key": "cic_cc",
                "bank_slug": "cic",
                "name": "CIC C/C",
                "account_type": Account.AccountType.CURRENT,
                "currency": "EUR",
                "subtype": "checking",
                "iban": "FR00 0000 0000 0000 0000 C",
                "bic": "CMCIFRPP",
            },
            {
                "key": "cic_livret_a",
                "bank_slug": "cic",
                "name": "CIC Livret A",
                "account_type": Account.AccountType.SAVINGS,
                "currency": "EUR",
                "subtype": "savings",
                "interest_rate": "1.00",
                "account_reference": "",
            },
            # ── Boursorama ───────────────────────────────────────────────────
            {
                "key": "boursorama_cc",
                "bank_slug": "boursorama",
                "name": "Boursorama C/C",
                "account_type": Account.AccountType.CURRENT,
                "currency": "EUR",
                "subtype": "checking",
                "iban": "FR00 0000 0000 0000 0000 B",
                "bic": "BOUSFRPP",
            },
            {
                "key": "boursorama_epargne",
                "bank_slug": "boursorama",
                "name": "Boursorama Épargne",
                "account_type": Account.AccountType.SAVINGS,
                "currency": "EUR",
                "subtype": "savings",
                "interest_rate": "3.00",
                "account_reference": "",
            },
        ]

        created_count = 0
        updated_count = 0
        accounts = {}

        for data in accounts_data:
            bank = banks[data["bank_slug"]]

            account, created = Account.objects.update_or_create(
                bank=bank,
                name=data["name"],
                defaults={
                    "account_type": data["account_type"],
                    "currency": data["currency"],
                    "is_active": True,
                },
            )
            accounts[data["key"]] = account

            if created:
                created_count += 1
            else:
                updated_count += 1

            # update_or_create on the sub-type — account IS the primary key,
            # so lookup=account is sufficient and always unique.
            if data["subtype"] == "checking":
                CheckingAccount.objects.update_or_create(
                    account=account,
                    defaults={
                        "iban": data.get("iban", ""),
                        "bic": data.get("bic", ""),
                    },
                )
            elif data["subtype"] == "savings":
                SavingsAccount.objects.update_or_create(
                    account=account,
                    defaults={
                        "interest_rate": data.get("interest_rate", "0"),
                        "account_reference": data.get("account_reference", ""),
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"  Accounts:      {created_count} created, {updated_count} updated"
            )
        )

        return accounts

    # =========================================================================
    # Step 4 — Cards
    # =========================================================================

    def _seed_cards(self, accounts):
        """
        Creates/updates payment cards linked to CheckingAccounts.

        Why cards need users:
            Card.user is a FK — each card belongs to one cardholder.
            Emmanuel = the superuser (SUPERUSER_EMAIL from .env).
            Carys    = a regular secondary user, created here if absent.

        If SUPERUSER_EMAIL is not in the DB (create-superuser not run yet),
        the command warns and skips card creation entirely.

        last_four values are fake placeholders (0001–0004).
        """
        User = get_user_model()

        # ── Retrieve Emmanuel (superuser) ─────────────────────────────────
        superuser_email = config("SUPERUSER_EMAIL")
        try:
            emmanuel = User.objects.get(email=superuser_email)
        except User.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ User {superuser_email} not found — run `make create-superuser` first. "
                    "Skipping cards."
                )
            )
            return

        # ── Create or retrieve Carys ──────────────────────────────────────
        # Minimal user — no password set (she'll log in via a future invite flow).
        # set_unusable_password(): Django's way to say "account exists but cannot
        # log in yet" — safer than setting a dummy password that could be guessed.
        carys, carys_created = User.objects.get_or_create(
            email="carys@home.local",
            defaults={
                "first_name": "Carys",
                "is_active": True,
            },
        )
        if carys_created:
            carys.set_unusable_password()
            carys.save()
            self.stdout.write(
                self.style.SUCCESS("  Carys user created (carys@home.local)")
            )

        # ── Retrieve CheckingAccount sub-type instances for the FK ────────
        # Card.checking_account is FK to CheckingAccount, not Account.
        yuh_ca = CheckingAccount.objects.get(account=accounts["yuh_cc"])
        ubs_ca = CheckingAccount.objects.get(account=accounts["ubs_cc"])
        cic_ca = CheckingAccount.objects.get(account=accounts["cic_cc"])

        # Each tuple: (user, CheckingAccount, last_four, card_type)
        cards_data = [
            (emmanuel, yuh_ca, "0001", Card.CardType.DEBIT),
            (emmanuel, ubs_ca, "0002", Card.CardType.DEBIT),
            (carys, ubs_ca, "0003", Card.CardType.DEBIT),
            (emmanuel, cic_ca, "0004", Card.CardType.DEBIT),
        ]

        created_count = 0
        updated_count = 0

        for user, checking_account, last_four, card_type in cards_data:
            # Lookup key: (user, checking_account, last_four)
            # Distinguishes debit vs credit if the same user has two cards
            # on the same account (last_four would differ in real data).
            _, created = Card.objects.update_or_create(
                user=user,
                checking_account=checking_account,
                last_four=last_four,
                defaults={
                    "card_type": card_type,
                    "is_active": True,
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Cards:         {created_count} created, {updated_count} updated"
            )
        )
