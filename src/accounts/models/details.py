"""
accounts/models/details.py — Tous les sous-modèles OneToOne d'Account.

Pattern commun : OneToOne → Account, primary_key=True, CASCADE.
Chaque sous-modèle porte les champs propres à un type d'enveloppe.
Montants en Decimal — jamais float (SR-002).

  CheckingAccount      — compte courant (IBAN, BIC)
  SavingsAccount       — livret / épargne (taux, référence)
  LifeInsuranceDetails — assurance vie (fonds euro, frais)
  PensionDetails       — pilier 3a / LPP (plafond, versements, frais)
"""

from decimal import Decimal

from django.db import models

from .account import Account

# =============================================================================
# CheckingAccount
# =============================================================================


class CheckingAccount(models.Model):
    """
    Fields specific to checking accounts (Yuh CHF, CIC C/C...).

    Why OneToOne instead of Django model inheritance?
    -------------------------------------------------
    Django's model inheritance creates automatic SQL joins that can be slow
    and hard to debug. An explicit OneToOne gives us full control over the
    join and keeps the SQL transparent.
    """

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="checking_account",
    )

    # IBAN: International Bank Account Number — e.g. CH56 0483 5012 3456 7800 9
    # null=True + unique=True : plusieurs comptes sans IBAN sont autorisés (NULL != NULL en SQL).
    iban = models.CharField(
        max_length=34, unique=True, null=True, blank=True, default=None
    )

    # BIC/SWIFT — optionnel, souvent absent des exports.
    bic = models.CharField(max_length=11, blank=True, default="")

    class Meta:
        verbose_name = "checking account"
        verbose_name_plural = "checking accounts"

    def __str__(self) -> str:
        return f"CheckingAccount — {self.account.name}"

    @property
    def is_complete(self) -> bool:
        """True si les champs bancaires essentiels sont renseignés (IBAN + BIC)."""
        return bool(self.iban and self.bic)


# =============================================================================
# SavingsAccount
# =============================================================================


class SavingsAccount(models.Model):
    """
    Fields specific to savings accounts (CIC Livret A, CIC LDDS, UBS épargne...).

    No IBAN — savings accounts don't participate in SEPA transfers.
    account_reference: optional free-text (CIC internal number, etc.) — never used
    as a lookup key, purely informational.
    """

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="savings_account",
    )

    # APY in % — e.g. 3.00 means 3% per year. Decimal pour éviter 2.9999… (SR-002).
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        blank=True,
    )

    account_reference = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        verbose_name = "savings account"
        verbose_name_plural = "savings accounts"

    def __str__(self) -> str:
        return f"SavingsAccount — {self.account.name} ({self.interest_rate}% APY)"

    @property
    def is_complete(self) -> bool:
        """True si le taux d'intérêt est renseigné (non nul)."""
        return self.interest_rate is not None and self.interest_rate > 0


# =============================================================================
# LifeInsuranceDetails
# =============================================================================


class LifeInsuranceDetails(models.Model):
    """
    Spécificités d'une assurance vie (INSURANCE).

    Le fonds euro est un capital garanti à taux fixe — PAS un Asset (pas de prix
    de marché ni d'ISIN). Sa valorisation s'additionne aux UC (Positions, Phase 3B)
    pour obtenir la valeur totale de l'AV. D-026 § fonds euro.
    """

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="life_insurance_details",
    )

    # Solde du fonds euro en devise du compte.
    fonds_euro_balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )

    # Taux de rendement annuel du fonds euro en % (ex : 2.30 pour 2,30 %).
    fonds_euro_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    # Frais de gestion annuels de l'enveloppe AV en %.
    management_fee_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "life insurance details"
        verbose_name_plural = "life insurance details"

    def __str__(self) -> str:
        balance = self.fonds_euro_balance or Decimal("0")
        return f"LifeInsuranceDetails — {self.account.name} (fonds euro : {balance})"


# =============================================================================
# PensionDetails
# =============================================================================


class PensionDetails(models.Model):
    """
    Spécificités d'un compte de prévoyance (PENSION_3A ou PENSION_LP / LPP).

    annual_limit_chf : plafond légal de déduction annuelle (ex : 7 056 CHF pour le
    3e pilier A en 2024). Pour la future jauge « il te reste X CHF » (Phase 3D).
    """

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="pension_details",
    )

    # Plafond légal annuel en CHF (3a : ~7 056 CHF, LPP : variable).
    annual_limit_chf = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    # Versements cumulés depuis le 1er janvier.
    contributions_ytd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    # Frais de gestion annuels de l'enveloppe en %.
    management_fee_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "pension details"
        verbose_name_plural = "pension details"

    def __str__(self) -> str:
        return f"PensionDetails — {self.account.name}"
