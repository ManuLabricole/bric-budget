"""
accounts/models/card.py — Card : carte de paiement liée à un CheckingAccount.

FK vers CheckingAccount (pas Account) : les cartes n'existent que sur les
comptes courants. Un CheckingAccount peut avoir N cartes (Emmanuel + Carys).
Le lien Card ↔ User permet d'attribuer les transactions à un porteur spécifique.
"""

from django.conf import settings
from django.db import models

from .details import CheckingAccount


class Card(models.Model):
    """
    A debit or credit card belonging to a user, linked to a CheckingAccount.

    One CheckingAccount can have multiple cards (Emmanuel + Carys on Yuh = 2 rows).
    Phase 6 : détails complémentaires (PAN complet, expiry, réseau…) si besoin.
    """

    checking_account = models.ForeignKey(
        CheckingAccount,
        on_delete=models.CASCADE,
        related_name="cards",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cards",
    )

    # Last 4 digits — enough to identify a card without storing sensitive data.
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

    def __str__(self) -> str:
        return f"{self.get_card_type_display()} *{self.last_four} — {self.user.email}"
