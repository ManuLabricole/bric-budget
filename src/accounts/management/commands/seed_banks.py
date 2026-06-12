"""
accounts/management/commands/seed_banks.py

Crée (ou met à jour) les Banks en DB depuis accounts/banks_config.py.

Usage :
    python manage.py seed_banks            # crée ou met à jour toutes les banques
    python manage.py seed_banks --dry-run  # affiche ce qui serait fait sans toucher la DB

Idempotent : peut être relancé autant de fois que nécessaire.
Si une banque existe déjà (même slug), ses champs sont mis à jour depuis la config.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.institutions_config import CATEGORIES, KNOWN_INSTITUTIONS
from accounts.models import Institution


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

        created_count = 0
        updated_count = 0

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

            bank, created = Institution.objects.update_or_create(
                slug=slug,
                defaults=defaults,
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓  Bank « {bank.name} » créée")
                )
            else:
                updated_count += 1
                self.stdout.write(f"  ·  Bank « {bank.name} » mise à jour")

        if not dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓  {created_count} créée(s), {updated_count} mise(s) à jour."
                )
            )
