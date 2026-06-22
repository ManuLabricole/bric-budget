"""
demo/management/commands/dev_reset.py — DEV ONLY (#118).

Supprime les comptes de démo et leurs données (transactions, imports, snapshots,
cartes). Garde le user démo → re-login possible après un nouveau dev_seed.

Usage :
    python manage.py dev_reset          # demande confirmation
    python manage.py dev_reset --yes    # sans confirmation (scripting)
"""

from django.core.management.base import BaseCommand

from transactions.management._dev_guard import (
    add_force_prod_argument,
    assert_dev_environment,
)


class Command(BaseCommand):
    help = "DEV ONLY — Supprime les comptes et données de démo (garde le user démo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Ne pas demander de confirmation (scripting).",
        )
        add_force_prod_argument(parser)

    def handle(self, *args, **options):
        if not options.get("force_prod"):
            assert_dev_environment("dev_reset")

        if not options["yes"]:
            confirm = input("Supprimer toutes les données de démo ? [y/N] ")
            if confirm.strip().lower() not in ("y", "yes", "o", "oui"):
                self.stdout.write("Annulé.")
                return

        from demo.seeder import reset_demo

        email = reset_demo()
        self.stdout.write(
            self.style.SUCCESS(f"✓ Données de démo supprimées (user {email} conservé).")
        )
