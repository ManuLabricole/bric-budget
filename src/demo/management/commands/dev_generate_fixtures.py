"""
demo/management/commands/dev_generate_fixtures.py — DEV ONLY (#118).

(Re)génère les fixtures bancaires synthétiques COMMITTÉES dans demo/fixtures/.
Anchor FIXE → fichiers stables (pas de churn git). Ces fixtures servent à
`dev_seed --from-fixtures` et pourront être déposées sur le bucket Railway.

Usage :
    python manage.py dev_generate_fixtures
    python manage.py dev_generate_fixtures --months 6
"""

from datetime import date

from django.core.management.base import BaseCommand

from transactions.management._dev_guard import (
    add_force_prod_argument,
    assert_dev_environment,
)

# Anchor FIXE : les fixtures committées ne doivent pas changer à chaque run
# (sinon diff git permanent). On choisit une date de référence stable.
FIXTURE_ANCHOR = date(2026, 6, 1)


class Command(BaseCommand):
    help = "DEV ONLY — (Re)génère les fixtures bancaires synthétiques (demo/fixtures/)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--months",
            type=int,
            default=12,
            help="Nombre de mois par fixture (défaut: 12).",
        )
        add_force_prod_argument(parser)

    def handle(self, *args, **options):
        if not options.get("force_prod"):
            assert_dev_environment("dev_generate_fixtures")

        from demo import generators
        from demo.seeder import FIXTURES_DIR

        paths = generators.write_fixtures(
            FIXTURES_DIR, anchor=FIXTURE_ANCHOR, months=options["months"]
        )
        for path in paths:
            self.stdout.write(
                self.style.SUCCESS(f"✓ {path.relative_to(FIXTURES_DIR.parent)}")
            )
        self.stdout.write(f"  Anchor : {FIXTURE_ANCHOR} · {len(paths)} fichiers.")
