"""
transactions/management/commands/sync_reference_data.py — parapluie référentiels (#126).

LA commande du release deploy : `migrate && sync_reference_data` (Railway, #135).
Enchaîne les seeds idempotents dans l'ordre de dépendance et fait remonter le
moindre échec en CommandError (exit ≠ 0) → le deploy est marqué FAILED, jamais
de prod silencieusement désynchronisée.

Ajouter un référentiel = 1 entrée dans REFERENCE_SEEDS + sa commande seed
idempotente (update_or_create) + ses données dans src/reference/ — convention
actée issue #126 (cf. reference/__init__.py).

Usage :
    python manage.py sync_reference_data [--dry-run]
"""

import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

# Ordre de dépendance : les institutions d'abord (les catégories n'en dépendent
# pas aujourd'hui, mais les futurs référentiels — plafonds, régimes fiscaux —
# pourront référencer les institutions).
REFERENCE_SEEDS = ("seed_banks", "seed_categories")


class Command(BaseCommand):
    help = (
        "Synchronise TOUS les référentiels (idempotent) — "
        "pensé pour le release deploy : échec = exit ≠ 0."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Propagé à chaque seed : affiche, n'écrit rien.",
        )

    def handle(self, *args, **options):
        flags = ["--dry-run"] if options["dry_run"] else []

        for name in REFERENCE_SEEDS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"── {name} ──"))
            try:
                call_command(name, *flags, stdout=self.stdout)
            except Exception as exc:
                logger.exception("sync_reference_data failed seed=%s", name)
                raise CommandError(f"{name} a échoué : {exc}") from exc

        logger.info(
            "sync_reference_data ok seeds=%s dry_run=%s",
            ",".join(REFERENCE_SEEDS),
            options["dry_run"],
        )
        self.stdout.write(self.style.SUCCESS("✓ Référentiels synchronisés."))
