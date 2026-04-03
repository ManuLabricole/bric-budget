"""
accounts/models.py — Banking infrastructure for BricBudget

Model dependency order (follow this when reading or extending):
    Bank → Account → CheckingAccount → Card (→ User)
                   → BalanceSnapshot
    ExchangeRate (standalone)
"""

from django.db import models

# =============================================================================
# Bank — A financial institution
# =============================================================================


class Bank(models.Model):
    """
    A financial institution: Yuh, CIC, UBS, Monzo...

    slug: URL-friendly identifier derived from the name.
    Example: "Yuh" → "yuh", "CIC France" → "cic-france".
    Used in URLs and imports to identify a bank without its DB id.

    default_currency: the bank's native currency.
    Yuh → CHF, CIC → EUR, Monzo → GBP.
    Used as the default value when creating new accounts under this bank.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    # ISO 3166-1 alpha-2 country code: CH, FR, GB...
    country = models.CharField(max_length=2)

    # ISO 4217 currency code: CHF, EUR, GBP...
    default_currency = models.CharField(max_length=3)

    # Icon identifier mapped to a file in static/icons/banks/miniature/<icon_slug>.[svg|png]
    # Example: "yuh", "cic", "ubs", "finpension"
    # Kept separate from slug so the icon can differ from the URL identifier.
    # Extension varies: .svg for cic/ubs, .png for yuh/finpension — resolve in template.
    # blank=True: optional — falls back to a generic bank icon in templates.
    icon_slug = models.CharField(max_length=50, blank=True, default="")

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "bank"
        verbose_name_plural = "banks"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.country})"


# =============================================================================
# Account — Generic bank account (base table)
# =============================================================================


class Account(models.Model):
    """
    Generic model representing any bank account.

    Why "generic"?
    --------------
    A Yuh checking account and a Finpension 3rd-pillar account share common
    fields (bank, name, currency, active) but also have very different ones.
    Common fields live here; type-specific fields live in dedicated tables:
    CheckingAccount, SavingsAccount, PensionAccount... (Phase 4+)

    The `account_type` field is a discriminator: it tells which specialised
    table holds the details for this account.
    Example: account_type="checking" → look up CheckingAccount(account=this)
    """

    class AccountType(models.TextChoices):
        # Phase 0A — implemented now
        CHECKING = "checking", "Checking account"
        # Phase 4 — specialised tables to be created later
        SAVINGS = "savings", "Savings account"
        PENSION_3A = "pension_3a", "3rd pillar (3a)"
        PENSION_LP = "pension_lp", "Vested benefits (LP)"
        # Phase 5
        INVESTMENT = "investment", "Investment account"

    bank = models.ForeignKey(
        Bank,
        on_delete=models.PROTECT,  # PROTECT: prevents deleting a bank that has accounts
        related_name="accounts",
    )

    name = models.CharField(max_length=200)

    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
    )

    # ISO 4217 currency code: CHF, EUR, GBP...
    currency = models.CharField(max_length=3)

    # Bank-assigned contract number — used by import connectors to match a file to an account.
    # Each bank uses its own format:
    #   CIC : "100961802700064764601" (RIB without spaces)
    #   UBS : not needed (IBAN in export file, stored in CheckingAccount.iban)
    #   Yuh : not needed (single account, matched by bank slug)
    # blank=True: optional — not all banks expose a contract number in their exports.
    contract_number = models.CharField(max_length=100, blank=True, default="")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(
        auto_now_add=True
    )  # set automatically on creation

    class Meta:
        verbose_name = "account"
        verbose_name_plural = "accounts"
        ordering = ["bank__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.currency}) — {self.bank.name}"


# =============================================================================
# CheckingAccount — Account specialisation for current/checking accounts
# =============================================================================


class CheckingAccount(models.Model):
    """
    Fields specific to checking accounts (Yuh CHF, CIC C/C...).

    Why OneToOne instead of Django model inheritance?
    -------------------------------------------------
    Django's model inheritance creates automatic SQL joins that can be slow
    and hard to debug. An explicit OneToOne gives us full control over the
    join and keeps the SQL transparent.

    Access patterns:
        account.checking_account.iban   ← from an Account instance
        ca.account.name                 ← from a CheckingAccount instance

    Phase 4+: SavingsAccount, PensionAccount3a, etc. will follow the same
    pattern — each with its own business-specific fields.
    """

    # primary_key=True: no separate id column — CheckingAccount.id == Account.id.
    # Removes a redundant column and makes the one-to-one relationship explicit.
    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,  # CASCADE: deleting the Account also deletes this
        primary_key=True,
        related_name="checking_account",
    )

    # IBAN: International Bank Account Number — e.g. CH56 0483 5012 3456 7800 9
    # blank=True + default="": optional (Finpension accounts may not have one)
    iban = models.CharField(max_length=34, blank=True, default="")

    # BIC/SWIFT: bank identifier used in international transfers — e.g. YUHHCHZZ for Yuh
    bic = models.CharField(max_length=11, blank=True, default="")

    class Meta:
        verbose_name = "checking account"
        verbose_name_plural = "checking accounts"

    def __str__(self):
        return f"CheckingAccount — {self.account.name}"


# =============================================================================
# SavingsAccount — Account specialisation for savings accounts (Livret A, LDDS...)
# =============================================================================


class SavingsAccount(models.Model):
    """
    Fields specific to savings accounts (CIC Livret A, CIC LDDS, Finpension...).

    Follows the exact same pattern as CheckingAccount: OneToOne → Account.
    No IBAN here — savings accounts don't participate in SEPA transfers.
    The account is identified by bank + name, not by a banking standard number.

    account_reference: optional free-text reference (CIC internal account number,
    Finpension contract number, etc.). Useful for display and future connectors,
    but never used as a lookup key — the Account FK is the real identifier.

    interest_rate: Annual Percentage Yield (APY) as a percentage.
    Example: 3.00 for the LDDS (3%), 0.50 for Livret A (0.5%).
    Stored as Decimal for precision (floating point would give 2.9999... rounding errors).
    blank=True + default=0: some savings accounts have no fixed rate (e.g. pension funds).
    """

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,  # CASCADE: deleting the Account also deletes this
        primary_key=True,
        related_name="savings_account",
    )

    # APY in % — e.g. 3.00 means 3% per year
    # max_digits=5, decimal_places=2: supports rates from 0.00% to 999.99%
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        blank=True,
    )

    # Free-text reference — CIC account number, Finpension contract number, etc.
    # Not used as a lookup key — purely informational.
    account_reference = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        verbose_name = "savings account"
        verbose_name_plural = "savings accounts"

    def __str__(self):
        return f"SavingsAccount — {self.account.name} ({self.interest_rate}% APY)"


# =============================================================================
# Card — A payment card linked to a CheckingAccount
# =============================================================================


class Card(models.Model):
    """
    A debit or credit card belonging to a user, linked to a CheckingAccount.

    Why FK to CheckingAccount instead of Account?
    ---------------------------------------------
    Cards only exist on checking accounts — not on savings or pension accounts.
    Pointing directly to CheckingAccount enforces this constraint at the DB level:
    it's impossible to accidentally link a card to a Finpension account.

    One CheckingAccount can have multiple cards (Emmanuel + Carys on Yuh = 2 rows).
    One user can also have multiple cards (debit + credit on the same account).

    Phase 6: additional card details (full PAN, expiry, issuer network...) will be
    added here when needed. Not now — YAGNI.
    """

    from django.conf import settings

    checking_account = models.ForeignKey(
        CheckingAccount,
        on_delete=models.CASCADE,  # CASCADE: deleting the CheckingAccount removes its cards
        related_name="cards",
    )

    # The cardholder — one card belongs to exactly one user
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # PROTECT: don't delete a user who still has cards
        related_name="cards",
    )

    # Last 4 digits — enough to identify a card without storing sensitive data
    # Example: "4521" for **** **** **** 4521
    last_four = models.CharField(max_length=4)

    class CardType(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    card_type = models.CharField(
        max_length=6,
        choices=CardType.choices,
        default=CardType.DEBIT,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "card"
        verbose_name_plural = "cards"
        ordering = ["checking_account", "last_four"]

    def __str__(self):
        return f"{self.get_card_type_display()} *{self.last_four} — {self.user.email}"


# =============================================================================
# BalanceSnapshot — Account balance at a point in time
# =============================================================================


class BalanceSnapshot(models.Model):
    """
    Captures the balance of an account on a given date.

    Created automatically on each file import.
    For Yuh: the balance is extracted from the CSV filename.
    Example: "Activités_2026_03_17 - 33,344.CSV" → 33 344 CHF on 2026-03-17

    balance_chf: balance converted to CHF (reference currency).
    Used to consolidate multi-currency net worth on charts.
    For accounts already in CHF, balance_chf == balance.
    """

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="balance_snapshots",
    )

    date = models.DateField()

    # max_digits=14: supports up to 999 billion — more than enough
    # decimal_places=2: cent-level precision
    balance = models.DecimalField(max_digits=14, decimal_places=2)

    # Currency of the raw balance — may differ from account.currency (rare)
    currency = models.CharField(max_length=3)

    # Balance converted to CHF via ExchangeRate — for consolidated charts
    # null=True: not yet converted if today's exchange rate hasn't been loaded
    balance_chf = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Source(models.TextChoices):
        IMPORT = "import", "File import"
        MANUAL = "manual", "Manual entry"

    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.IMPORT,
    )

    class Meta:
        verbose_name = "balance snapshot"
        verbose_name_plural = "balance snapshots"
        ordering = ["-date"]
        # One snapshot per account per date
        unique_together = [("account", "date")]

    def __str__(self):
        return f"{self.account.name} — {self.date} : {self.balance} {self.currency}"


# =============================================================================
# ExchangeRate — Currency exchange rate on a given date
# =============================================================================


class ExchangeRate(models.Model):
    """
    Exchange rate between two currencies on a specific date.

    Populated automatically via the frankfurter.app API at import time.
    We store rates rather than fetching them live so that:
    - historical balance_chf values never change retroactively
    - the app works offline after rates are fetched once

    Usage example:
        EUR → CHF on 2026-03-17: rate = 0.9321
        balance_chf = balance_eur * rate

    The canonical pair is always (from_currency → CHF), but we store the
    full pair so we can query in both directions if needed.
    """

    date = models.DateField()

    # ISO 4217 currency codes
    from_currency = models.CharField(max_length=3)
    to_currency = models.CharField(max_length=3)

    # The rate: 1 unit of from_currency = rate units of to_currency
    # max_digits=12, decimal_places=6: handles micro-currencies and crypto if needed
    rate = models.DecimalField(max_digits=12, decimal_places=6)

    class Meta:
        verbose_name = "exchange rate"
        verbose_name_plural = "exchange rates"
        ordering = ["-date"]
        # One rate per currency pair per day
        unique_together = [("date", "from_currency", "to_currency")]

    def __str__(self):
        return f"{self.date} | 1 {self.from_currency} = {self.rate} {self.to_currency}"
