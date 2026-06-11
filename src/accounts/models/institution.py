"""accounts/models/institution.py — Institution financière.

Une Institution couvre tout établissement qui héberge un compte/enveloppe :
banque (Yuh, UBS, CIC), fondation de prévoyance (Finpension), exchange crypto
(Binance), assureur (Spirica)... — pas seulement des banques. D'où le nom
générique `Institution` plutôt que `Bank`.
"""

from django.db import models

# =============================================================================
# Institution — A financial institution (bank, pension foundation, exchange...)
# =============================================================================


class Institution(models.Model):
    """
    A financial institution: Yuh, CIC, UBS, Finpension, Binance, Spirica...

    slug: URL-friendly identifier derived from the name.
    Example: "Yuh" → "yuh", "CIC France" → "cic-france".
    Used in URLs and imports to identify a bank without its DB id.

    default_currency: the bank's native currency.
    Yuh → CHF, CIC → EUR, Monzo → GBP.
    Used as the default value when creating new accounts under this bank.

    category: coarse type for the UI badge (banque / investissement / crypto).
    Source de vérité = institutions_config.py, posé par seed_banks.
    """

    class Category(models.TextChoices):
        BANK = "bank", "Banque"
        INVESTMENT = "investment", "Investissement"
        CRYPTO = "crypto", "Crypto"

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    # ISO 3166-1 alpha-2 country code: CH, FR, GB...
    country = models.CharField(max_length=2)

    # ISO 4217 currency code: CHF, EUR, GBP...
    default_currency = models.CharField(max_length=3)

    # Badge UI grossier : banque / investissement / crypto (assurance vie et
    # prévoyance rangées en "investment" — leur spécificité fiscale vit au niveau
    # du compte, pas de l'institution). Rempli par seed_banks depuis la config.
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.BANK,
    )

    # Icon identifier mapped to a file in static/icons/banks/miniature/<icon_slug>.png
    # Example: "yuh", "cic", "ubs". Kept separate from slug so icon can differ from URL slug.
    # blank=True: optional — falls back to initiale in templates.
    icon_slug = models.CharField(max_length=50, blank=True, default="")

    # Domain used to fetch the logo via Google Favicons API.
    # Example: "yuh.ch", "ubs.com", "cic.fr"
    # Used by the backfill_logos management command (services/logos.py).
    # blank=True: optional — logo won't be fetched if empty.
    domain = models.CharField(max_length=100, blank=True, default="")

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "institution"
        verbose_name_plural = "institutions"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.country})"
