"""
accounts/signals.py — auto-fetch du logo au save d'une Institution.

« Au fil de l'eau » : créer/modifier une Institution avec un `domain` et sans
logo sur disque déclenche le téléchargement (services/logos.py). Best-effort :
fetch_logo ne lève jamais (contrat du service) → un échec réseau ne fait
JAMAIS échouer le save. Le one-shot initial / la réparation passent par la
commande backfill_logos.

Câblé dans AccountsConfig.ready() (apps.py).
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Institution
from services import logos


@receiver(post_save, sender=Institution, dispatch_uid="institution_logo_autofetch")
def fetch_institution_logo(sender, instance: Institution, **kwargs) -> None:
    if not instance.domain:
        return

    # Même fallback que bank_icon_url : icon_slug, sinon slug.
    slug = instance.icon_slug or instance.slug
    base = logos.banks_icon_base()
    if logos.has_logo(slug, base):
        return

    logos.fetch_logo(instance.domain, base / "miniature" / f"{slug}.png")
