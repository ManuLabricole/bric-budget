"""accounts/models/bank.py — Bank : une institution financière."""

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

    # Icon identifier mapped to a file in static/icons/banks/miniature/<icon_slug>.png
    # Example: "yuh", "cic", "ubs". Kept separate from slug so icon can differ from URL slug.
    # blank=True: optional — falls back to initiale in templates.
    icon_slug = models.CharField(max_length=50, blank=True, default="")

    # Domain used to fetch the logo via Google Favicons API.
    # Example: "yuh.ch", "ubs.com", "cic.fr"
    # Used by the update_bank_logos management command.
    # blank=True: optional — logo won't be fetched if empty.
    domain = models.CharField(max_length=100, blank=True, default="")

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "bank"
        verbose_name_plural = "banks"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.country})"
