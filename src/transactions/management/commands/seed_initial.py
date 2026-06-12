"""
transactions/management/commands/seed_initial.py

Bootstrap dev des RÉFÉRENTIELS (`make seed`) — catégories + institutions.
Délègue à la commande canonique `sync_reference_data` (idempotente, atomique,
échec bruyant — #126). Aucune logique propre : un seul point de vérité par
référentiel (seed_categories, seed_banks).

⛔ NE seede PAS les comptes/cartes personnels : ce sont des données de DEV
personnelles, pas un référentiel. Leur commande dédiée est `setup_accounts`
(import des relevés CSV/XLSX réels, IBAN via .env — SR-008).

Usage :
    python manage.py seed_initial
    make seed
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Seed dev des référentiels (catégories + institutions) via sync_reference_data."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== BricBudget seed_initial ==="))
        # Référentiels uniquement. Comptes/cartes perso → `setup_accounts`.
        call_command("sync_reference_data", stdout=self.stdout)
        self.stdout.write(
            self.style.SUCCESS(
                "=== Seed terminé — comptes perso : `python manage.py setup_accounts` ==="
            )
        )
