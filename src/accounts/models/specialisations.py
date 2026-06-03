"""
accounts/models/specialisations.py — Spécialisations OneToOne d'Account + Card.

CheckingAccount et SavingsAccount portent les champs propres à chaque type de
compte (pattern OneToOne → Account). Phase 3A ajoute LifeInsuranceDetails,
PensionDetails, CryptoDetails dans details.py — sans toucher ces deux-ci
(données prod existantes).
"""

from django.conf import settings
from django.db import models

from .account import Account

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
    # null=True + unique=True : plusieurs comptes sans IBAN sont autorisés (NULL != NULL en SQL).
    # blank=True : formulaire admin accepte un champ vide → stocké en NULL.
    # is_complete = False tant que l'IBAN n'est pas renseigné.
    iban = models.CharField(
        max_length=34, unique=True, null=True, blank=True, default=None
    )

    # BIC/SWIFT: bank identifier used in international transfers — e.g. YUHHCHZZ for Yuh
    # Optionnel : peut être dérivé de la banque, souvent absent des exports.
    bic = models.CharField(max_length=11, blank=True, default="")

    class Meta:
        verbose_name = "checking account"
        verbose_name_plural = "checking accounts"

    def __str__(self):
        return f"CheckingAccount — {self.account.name}"

    @property
    def is_complete(self):
        """True si les champs bancaires essentiels sont renseignés (IBAN + BIC)."""
        return bool(self.iban and self.bic)


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

    @property
    def is_complete(self):
        """True si le taux d'intérêt est renseigné (non nul)."""
        return self.interest_rate is not None and self.interest_rate > 0


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
