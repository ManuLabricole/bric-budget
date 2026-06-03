"""
accounts/models/details.py — Spécialisations OneToOne pour Phase 3A.

Deux nouveaux Details (en plus de CheckingAccount/SavingsAccount existants) :
  LifeInsuranceDetails  — assurance vie (fonds euro + frais enveloppe)
  PensionDetails        — 3e pilier (3a) et LPP (plafond, versements, frais)

Pattern identique à CheckingAccount/SavingsAccount : OneToOne → Account,
primary_key=True, CASCADE. Montants en Decimal — jamais float (SR-002).

CryptoDetails délibérément absent (D-026) : institution = exchange (Binance…),
wallet dans external_ref chiffré (Phase 3A-bis). Aucun champ propre nécessaire.
"""

from decimal import Decimal

from django.db import models

from .account import Account


class LifeInsuranceDetails(models.Model):
    """
    Spécificités d'une assurance vie (INSURANCE).

    Le fonds euro est un capital garanti à taux fixe — PAS un Asset (pas de prix
    de marché ni d'ISIN). Sa valorisation s'additionne aux UC (Positions, Phase 3B)
    pour obtenir la valeur totale de l'AV. D-026 § fonds euro.

    management_fee_pct : frais annuels de l'enveloppe (ex : 0.60 pour 0,60 %).
    Anticipé pour le calcul du coût total en Phase 3B/4A.
    """

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="life_insurance_details",
    )

    # Solde du fonds euro (capital garanti, en devise du compte).
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


class PensionDetails(models.Model):
    """
    Spécificités d'un compte de prévoyance (PENSION_3A ou PENSION_LP / LPP).

    annual_limit_chf : plafond légal de déduction annuelle (ex : 7 056 CHF pour le
    3e pilier A en 2024). Stocké ici pour la future jauge "il te reste X CHF à verser"
    (Phase 3D). Nullable car le LPP n'a pas de plafond unique.

    contributions_ytd : versements effectués depuis le début de l'année civile.
    Mis à jour à chaque import de relevé ou saisie manuelle.
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
