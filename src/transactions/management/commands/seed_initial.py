"""
transactions/management/commands/seed_initial.py

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

from decouple import config
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import Account, Card, CheckingAccount, Institution, SavingsAccount


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

        # Catégories : déléguées à la commande canonique (référentiel committé,
        # atomique, échec bruyant — #126). seed_initial ne garde que les données
        # dev personnelles (banques/comptes/cartes) dont il est le seul appelant.
        call_command("seed_categories", stdout=self.stdout)
        banks = self._seed_banks()
        accounts = self._seed_accounts(banks)
        self._seed_cards(accounts)

        self.stdout.write(self.style.SUCCESS("=== Seed complete ==="))

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

        # Each tuple: (name, slug, country, currency, icon_slug, domain)
        # domain : utilisé par `make backfill-logos` pour télécharger le logo
        #          via Google Favicons API (https://www.google.com/s2/favicons?domain=...)
        banks_data = [
            ("Yuh", "yuh", "CH", "CHF", "yuh", "yuh.ch"),
            ("UBS", "ubs", "CH", "CHF", "ubs", "ubs.com"),
            ("CIC", "cic", "FR", "EUR", "cic", "cic.fr"),
            ("Boursorama", "boursorama", "FR", "EUR", "boursorama", "boursorama.com"),
        ]

        created_count = 0
        updated_count = 0
        banks = {}

        for name, slug, country, currency, icon_slug, domain in banks_data:
            bank, created = Institution.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "country": country,
                    "default_currency": currency,
                    "icon_slug": icon_slug,
                    "domain": domain,
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
                "account_type": Account.AccountType.CHECKING,
                "currency": "CHF",
                "subtype": "checking",
                "iban": "CH00 0000 0000 0000 0000 Y",
                "bic": "",
            },
            # ── UBS ──────────────────────────────────────────────────────────
            # Les IBANs UBS sont lus depuis .env — jamais codés en dur.
            # Définir dans .env avant make seed :
            #   UBS_IBAN_NORMALISED = IBAN sans espaces (clé d'import via contract_number)
            #   UBS_IBAN_DISPLAY    = IBAN avec espaces (affiché dans l'UI / SEPA)
            {
                "key": "ubs_cc",
                "bank_slug": "ubs",
                "name": "UBS C/C",
                "account_type": Account.AccountType.CHECKING,
                "currency": "CHF",
                "subtype": "checking",
                "contract_number": config("UBS_IBAN_NORMALISED", default=""),
                "iban": config("UBS_IBAN_DISPLAY", default=""),
                "bic": "",
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
            # Les RIBs CIC sont lus depuis .env — jamais codés en dur.
            # Définir dans .env avant make seed :
            #   CIC_CC_CONTRACT      = RIB normalisé du compte courant
            #   CIC_LIVRET_CONTRACT  = RIB normalisé du Livret A
            #   CIC_LDDS_CONTRACT    = RIB normalisé du LDDS
            # Utilisé par CICConnector pour matcher chaque feuille Excel à un compte DB.
            {
                "key": "cic_cc",
                "bank_slug": "cic",
                "name": "CIC C/C",
                "account_type": Account.AccountType.CHECKING,
                "currency": "EUR",
                "contract_number": config("CIC_CC_CONTRACT", default=""),
                "subtype": "checking",
                "iban": "",
                "bic": "",
            },
            {
                "key": "cic_livret_a",
                "bank_slug": "cic",
                "name": "CIC Livret A",
                "account_type": Account.AccountType.SAVINGS,
                "currency": "EUR",
                "contract_number": config("CIC_LIVRET_CONTRACT", default=""),
                "subtype": "savings",
                "interest_rate": "3.00",
                "account_reference": "",
            },
            {
                "key": "cic_ldds",
                "bank_slug": "cic",
                "name": "CIC LDDS",
                "account_type": Account.AccountType.SAVINGS,
                "currency": "EUR",
                "contract_number": config("CIC_LDDS_CONTRACT", default=""),
                "subtype": "savings",
                "interest_rate": "3.00",
                "account_reference": "",
            },
            # ── Boursorama ───────────────────────────────────────────────────
            {
                "key": "boursorama_cc",
                "bank_slug": "boursorama",
                "name": "Boursorama C/C",
                "account_type": Account.AccountType.CHECKING,
                "currency": "EUR",
                "subtype": "checking",
                "iban": "FR00 0000 0000 0000 0000 B",
                "bic": "",
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
                institution=bank,
                name=data["name"],
                defaults={
                    "account_type": data["account_type"],
                    "currency": data["currency"],
                    "contract_number": data.get("contract_number", ""),
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

        last_four: real values extracted from CSV exports where known (Yuh: 1150, 8803).
        UBS and CIC still use placeholders until their card formats are analysed.
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

        # Each tuple: (user, CheckingAccount, last_four, card_type, is_active)
        # last_four values: real digits extracted from bank CSV exports.
        #   Yuh: CARD NUMBER column → "**** 1150" (Emmanuel), "**** 8803" (Carys)
        #   UBS: contract-number format, last_four not extractable → keep fake for now
        #   CIC: extracted from descriptions "CARTE XXXX"
        #
        # is_active=False for deactivated cards (lost/stolen/replaced).
        # These must stay in DB so historical transactions can be linked to a cardholder.
        cards_data = [
            (emmanuel, yuh_ca, "1150", Card.CardType.DEBIT, True),
            (carys, yuh_ca, "8803", Card.CardType.DEBIT, True),
            (
                emmanuel,
                ubs_ca,
                "0002",
                Card.CardType.DEBIT,
                True,
            ),  # TODO: real last_four unknown
            (
                carys,
                ubs_ca,
                "0003",
                Card.CardType.DEBIT,
                True,
            ),  # TODO: real last_four unknown
            (emmanuel, cic_ca, "8703", Card.CardType.DEBIT, True),  # current CIC card
            (
                emmanuel,
                cic_ca,
                "6673",
                Card.CardType.DEBIT,
                False,
            ),  # old CIC card (147 tx in history)
            (
                emmanuel,
                cic_ca,
                "0042",
                Card.CardType.DEBIT,
                False,
            ),  # very old CIC card (2 tx)
        ]

        created_count = 0
        updated_count = 0

        for user, checking_account, last_four, card_type, is_active in cards_data:
            # Lookup key: (user, checking_account, last_four) — unique per physical card.
            # Using last_four in the lookup (not just defaults) allows one user to have
            # multiple cards on the same account (active current + deactivated old ones).
            _, created = Card.objects.update_or_create(
                user=user,
                checking_account=checking_account,
                last_four=last_four,
                defaults={
                    "card_type": card_type,
                    "is_active": is_active,
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
