"""
accounts/management/commands/seed_banks.py

Crée (ou met à jour) les Banks en DB depuis accounts/banks_config.py.

Usage :
    python manage.py seed_banks            # crée ou met à jour toutes les banques
    python manage.py seed_banks --dry-run  # affiche ce qui serait fait sans toucher la DB

Idempotent : peut être relancé autant de fois que nécessaire.
Si une banque existe déjà (même slug), ses champs sont mis à jour depuis la config.
"""

from django.core.management.base import BaseCommand

from accounts.banks_config import KNOWN_BANKS
from accounts.models import Bank


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

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Mode dry-run — aucune modification.\n")
            )

        created_count = 0
        updated_count = 0

        for slug, config in KNOWN_BANKS.items():
            defaults = {
                "name": config["name"],
                "icon_slug": slug,  # icon_slug == slug par convention
                "default_currency": config["currency"],
                "country": config.get("country", ""),
            }

            if dry_run:
                exists = Bank.objects.filter(slug=slug).exists()
                action = "·  déjà en DB" if exists else "✓  à créer"
                self.stdout.write(f"  {action}  {config['name']} ({slug})")
                continue

            bank, created = Bank.objects.update_or_create(
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
