"""
demo/management/commands/dev_seed.py — DEV ONLY (#118).

Seed une DB de démo complète VIA le vrai pipeline d'import : user loginable,
institutions + catégories, comptes (checking/livret/Yuh), carte, transactions
importées depuis des fichiers synthétiques (ImportLog + tx liées + fichier chiffré),
puis application des règles de catégorisation.

Usage :
    python manage.py dev_seed                 # 12 mois, génère les fichiers
    python manage.py dev_seed --flush         # repart de zéro (comptes démo)
    python manage.py dev_seed --months 6
    python manage.py dev_seed --from-fixtures # importe demo/fixtures/ (committées)
"""

from django.core.management.base import BaseCommand

from transactions.management._dev_guard import (
    add_force_prod_argument,
    assert_dev_environment,
)


class Command(BaseCommand):
    help = "DEV ONLY — Seed une DB de démo via le pipeline d'import (user, comptes, imports, règles)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Supprime les données démo existantes avant le seed.",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=12,
            help="Nombre de mois de données à générer (défaut: 12).",
        )
        parser.add_argument(
            "--from-fixtures",
            action="store_true",
            help="Importe les fixtures committées (demo/fixtures/) au lieu de générer.",
        )
        add_force_prod_argument(parser)

    def handle(self, *args, **options):
        if not options.get("force_prod"):
            assert_dev_environment("dev_seed")

        # Import tardif : la logique vit dans le package (commande mince).
        from demo.seeder import seed_demo

        summary = seed_demo(
            flush=options["flush"],
            months=options["months"],
            from_fixtures=options["from_fixtures"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Démo : user {summary.user_email} · {summary.accounts} comptes · "
                f"{summary.rules} règles · {summary.imports} imports · "
                f"{summary.created} transactions créées (skipped {summary.skipped})"
            )
        )
        self.stdout.write("  Login : DEMO_USER_EMAIL / DEMO_USER_PASSWORD du .env.")
