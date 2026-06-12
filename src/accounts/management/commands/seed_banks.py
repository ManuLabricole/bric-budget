"""
accounts/management/commands/seed_banks.py

Crée (ou met à jour) les Banks en DB depuis accounts/banks_config.py.

Usage :
    python manage.py seed_banks            # crée ou met à jour toutes les banques
    python manage.py seed_banks --dry-run  # affiche ce qui serait fait sans toucher la DB

Idempotent : peut être relancé autant de fois que nécessaire.
Si une banque existe déjà (même slug), ses champs sont mis à jour depuis la config.
"""

import logging

from django.core.management.base import BaseCommand, CommandError

from accounts.institutions_config import CATEGORIES, KNOWN_INSTITUTIONS
from accounts.models import Institution
from services.reference_sync import SyncResult, sync_record

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Crée ou met à jour les Banks depuis banks_config.py."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait fait sans modifier la DB.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Garde-fou : une category hors du set autorisé (typo dans la config) serait
        # sinon écrite en silence (PostgreSQL n'applique pas `choices`). On échoue net.
        invalid = {
            slug: cfg.get("category")
            for slug, cfg in KNOWN_INSTITUTIONS.items()
            if cfg.get("category") not in CATEGORIES
        }
        if invalid:
            raise CommandError(f"Catégories invalides dans la config : {invalid}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Mode dry-run — aucune modification.\n")
            )

        counts = {r: 0 for r in SyncResult}

        for slug, config in KNOWN_INSTITUTIONS.items():
            defaults = {
                "name": config["name"],
                "icon_slug": slug,  # icon_slug == slug par convention
                "default_currency": config["currency"],
                "country": config.get("country", ""),
                # domain → récupération auto du logo (post_save + backfill_logos).
                "domain": config.get("domain", ""),
                # category → badge UI (bank / investment / crypto).
                "category": config.get("category", "bank"),
            }

            if dry_run:
                exists = Institution.objects.filter(slug=slug).exists()
                action = "·  déjà en DB" if exists else "✓  à créer"
                self.stdout.write(f"  {action}  {config['name']} ({slug})")
                continue

            institution, result = sync_record(
                Institution, lookup={"slug": slug}, defaults=defaults
            )
            counts[result] += 1
            if result is SyncResult.CREATED:
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓  « {institution.name} » créée")
                )
            elif result is SyncResult.UPDATED:
                self.stdout.write(f"  ~  « {institution.name} » modifiée")

        if not dry_run:
            logger.info(
                "seed_banks ok created=%s updated=%s unchanged=%s",
                counts[SyncResult.CREATED],
                counts[SyncResult.UPDATED],
                counts[SyncResult.UNCHANGED],
            )
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓  Institutions : {counts[SyncResult.CREATED]} créées · "
                    f"{counts[SyncResult.UPDATED]} modifiées · "
                    f"{counts[SyncResult.UNCHANGED]} inchangées"
                )
            )
