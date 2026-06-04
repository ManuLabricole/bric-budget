"""accounts/models/snapshot.py — BalanceSnapshot : solde d'un compte à une date."""

from django.db import models

from .account import Account

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

    # Solde extrait du fichier source (filename pour Yuh, metadata pour UBS/CIC).
    # null=True : si le connecteur ne peut pas extraire le solde (ex: Yuh avec
    # nom de fichier URL-encodé), on crée quand même le snapshot avec computed_balance.
    balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )

    # Solde recalculé = dernier snapshot connu + somme des nouvelles transactions.
    # Calculé par ImportService à chaque import. null=True sur le premier import
    # (pas de snapshot précédent = pas de base de calcul).
    computed_balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )

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

    @property
    def authoritative_balance(self):
        """Meilleur solde disponible : extrait si présent, sinon calculé."""
        return self.balance if self.balance is not None else self.computed_balance

    @property
    def drift(self):
        """
        Écart entre solde extrait et solde calculé.
        None si l'un des deux manque (premier import, ou extraction impossible).
        Un écart > 0.01 indique une anomalie (transaction manquante, arrondi banque...).
        """
        if self.balance is not None and self.computed_balance is not None:
            return self.balance - self.computed_balance
        return None
