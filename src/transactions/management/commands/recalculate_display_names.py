"""
transactions/management/commands/recalculate_display_names.py

Recomputes Transaction.display_name for all existing transactions using the
current _clean_description() logic from connectors/base.py.

When to run:
  - After the initial migration that adds the display_name field (all rows = "")
  - After improving _clean_description() to benefit from better cleaning instantly
  - Never needed for new imports — services.py populates display_name at import time

Usage:
  make recalculate-display-names
  python manage.py recalculate_display_names
  python manage.py recalculate_display_names --dry-run   # preview without writing
"""

from django.core.management.base import BaseCommand

from connectors.base import BaseConnector
from transactions.models import Transaction


class Command(BaseCommand):
    help = "Recompute display_name for all transactions from description_raw"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print before/after without saving to DB",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process only the first N transactions (for testing)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]

        # We instantiate a throwaway BaseConnector subclass just to access
        # _clean_description() — it's an instance method but has no state.
        # This avoids duplicating the logic here.
        class _Cleaner(BaseConnector):
            def parse(self, filepath):
                return []

        cleaner = _Cleaner()

        qs = Transaction.objects.all().order_by("id")
        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(
            f"Processing {total} transactions{'  [DRY RUN]' if dry_run else ''}..."
        )

        updated = 0
        unchanged = 0
        batch = []
        BATCH_SIZE = 500

        for tx in qs.iterator(chunk_size=BATCH_SIZE):
            new_display = cleaner._clean_description(tx.description_raw)

            if new_display == tx.display_name:
                unchanged += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"  [{tx.id}] {repr(tx.description_raw[:60])}\n"
                    f"       was: {repr(tx.display_name)}\n"
                    f"       now: {repr(new_display)}"
                )
            else:
                tx.display_name = new_display
                batch.append(tx)

            updated += 1

            if not dry_run and len(batch) >= BATCH_SIZE:
                Transaction.objects.bulk_update(batch, ["display_name"])
                batch.clear()

        if not dry_run and batch:
            Transaction.objects.bulk_update(batch, ["display_name"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {updated} updated, {unchanged} already correct"
                + (" (dry run, nothing saved)" if dry_run else "")
            )
        )
