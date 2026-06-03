"""accounts/models/fx.py — ExchangeRate : taux de change à une date (standalone)."""

from django.db import models

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
