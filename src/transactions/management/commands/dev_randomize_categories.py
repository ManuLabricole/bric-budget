"""
transactions/management/commands/dev_randomize_categories.py

DEV ONLY — Assigns random categories to transactions and ensures every active
category has at least one transaction.

Why this command exists:
    At import time, no CategorizationRules exist yet → every transaction
    lands in "Inconnu". The Budget UI is useless with 100% unknowns.
    This command seeds realistic-looking category distribution so we can
    test the UI layout, charts, and aggregation queries on real data.

    DO NOT run in production. This overwrites real categorization data.

Logic:
    Phase 1 — Random assignment:
        - Transactions with amount > 0 (income) → random pick from income categories:
            Revenus, Remboursements
        - Transactions with amount < 0 (expense) → random pick from all active
            categories EXCEPT: Revenus, Remboursements, Virements, Inconnu
        - categorization_source is set to "ai" as a visual marker in the UI
            ("AI CATEGORIZED" badge) so you always know this was dev-randomized.

    Phase 2 — Coverage guarantee:
        After random assignment, check which active categories have 0 transactions.
        For each uncovered category, steal one random transaction from the largest
        covered category and reassign it. This ensures every category appears in
        the UI — useful to test layout, charts, legend, etc.

Usage:
    python manage.py dev_randomize_categories
    python manage.py dev_randomize_categories --all   # re-randomize even already categorized
    make dev-randomize
    make dev-randomize ALL=1
"""

import random

from django.core.management.base import BaseCommand
from django.db.models import Count

from transactions.models import Category, SubCategory, Transaction

# Slugs of categories that should NEVER be assigned to expense transactions.
# - Revenus / Remboursements : income-only by semantic definition
# - Virements : internal transfers, must be set deliberately
# - Inconnu   : the fallback, not a "real" category
EXCLUDED_FROM_EXPENSES = {"revenus", "remboursements", "virements", "inconnu"}

# Slugs of categories used for income transactions (amount > 0)
INCOME_CATEGORY_SLUGS = {"revenus", "remboursements"}


class Command(BaseCommand):
    help = "DEV ONLY — Assigns random categories and ensures full category coverage"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-randomize ALL transactions, not just uncategorized ones",
        )
        from transactions.management._dev_guard import add_force_prod_argument

        add_force_prod_argument(parser)

    def handle(self, *args, **options):
        # ── 0. Refuser de tourner en prod (DEBUG=False) ───────────────────
        from transactions.management._dev_guard import assert_dev_environment

        if not options.get("force_prod"):
            assert_dev_environment("dev_randomize_categories")

        # ── 1. Safety warning ─────────────────────────────────────────────
        self.stdout.write(
            self.style.WARNING(
                "\n⚠  DEV ONLY — this command overwrites categorization data.\n"
                "   Never run in production.\n"
            )
        )

        # ── 2. Load categories from DB ────────────────────────────────────
        # Split into income pool vs expense pool (see constants above).
        all_categories = list(Category.objects.filter(is_active=True))

        income_pool = [c for c in all_categories if c.slug in INCOME_CATEGORY_SLUGS]
        expense_pool = [
            c for c in all_categories if c.slug not in EXCLUDED_FROM_EXPENSES
        ]

        if not income_pool or not expense_pool:
            self.stdout.write(
                self.style.ERROR(
                    "Income or expense category pool is empty. Did you run `make seed`?"
                )
            )
            return

        self.stdout.write(
            f"  Income pool : {len(income_pool)} categories "
            f"({', '.join(c.name for c in income_pool)})"
        )
        self.stdout.write(f"  Expense pool: {len(expense_pool)} categories")

        # ── Pré-charger les sous-catégories par catégorie ─────────────────
        # Un dict category_id → [SubCategory, ...] pour éviter les N+1 au moment
        # d'assigner une sous-catégorie aléatoire à chaque transaction.
        # Si une catégorie n'a pas de sous-catégorie active, subcat_map[id] = []
        # et subcategory sera laissé à None (comportement attendu).
        subcat_map: dict[int, list] = {}
        for sub in SubCategory.objects.filter(is_active=True).select_related(
            "category"
        ):
            subcat_map.setdefault(sub.category_id, []).append(sub)

        # ── 3. Select transactions to update ──────────────────────────────
        # --all : re-randomize every transaction, even already categorized ones.
        # default: only NULL category or "Inconnu".
        qs = Transaction.objects.select_related("category")

        if not options["all"]:
            qs = qs.filter(category__isnull=True) | qs.filter(
                category__slug__in={"inconnu"}
            )

        total = qs.count()
        if total == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nNothing to randomize. Use --all to re-randomize everything."
                )
            )
            # Still run coverage check in case categories are missing
        else:
            # ── 4. Phase 1 — Random assignment ────────────────────────────
            self.stdout.write(f"\n  Phase 1 — Randomizing {total} transactions...")

            updated = 0
            batch = []
            BATCH_SIZE = 500

            for tx in qs.iterator():
                chosen_cat = (
                    random.choice(income_pool)
                    if tx.amount > 0
                    else random.choice(expense_pool)
                )
                tx.category = chosen_cat

                # Assigner une sous-catégorie aléatoire parmi celles de la catégorie.
                # None si la catégorie n'a pas de sous-catégorie active.
                subcats = subcat_map.get(chosen_cat.id, [])
                tx.subcategory = random.choice(subcats) if subcats else None

                # "ai" badge = visual marker that this was dev-randomized
                tx.categorization_source = Transaction.CategorizationSource.AI
                batch.append(tx)
                updated += 1

                if len(batch) >= BATCH_SIZE:
                    Transaction.objects.bulk_update(
                        batch, ["category", "subcategory", "categorization_source"]
                    )
                    batch = []
                    self.stdout.write(f"    {updated}/{total}...")

            if batch:
                Transaction.objects.bulk_update(
                    batch, ["category", "subcategory", "categorization_source"]
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"  Phase 1 done — {updated} transactions randomized."
                )
            )

        # ── 5. Phase 2 — Coverage guarantee ──────────────────────────────
        # Every active non-system, non-excluded category must have ≥ 1 transaction.
        # We check expense categories (income pool only has 2, usually covered).
        #
        # Strategy: find uncovered categories, then "steal" one transaction from
        # the largest covered category and reassign it. We do this for each gap.
        # "Steal" means no new transactions are created — we rebalance existing ones.
        self.stdout.write("\n  Phase 2 — Coverage check...")

        # Count transactions per expense category
        covered = {
            row["category_id"]: row["count"]
            for row in (
                Transaction.objects.filter(category__in=expense_pool)
                .values("category_id")
                .annotate(count=Count("id"))
            )
        }

        uncovered = [c for c in expense_pool if c.id not in covered]
        covered_rich = sorted(
            [c for c in expense_pool if c.id in covered],
            key=lambda c: -covered[c.id],  # richest first
        )

        if not uncovered:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Phase 2 done — all {len(expense_pool)} expense categories covered."
                )
            )
        else:
            self.stdout.write(
                f"  {len(uncovered)} uncovered categories — stealing transactions..."
            )

            steal_batch = []
            rich_idx = 0  # cycle through rich categories to avoid emptying one

            for missing_cat in uncovered:
                if not covered_rich:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Cannot cover '{missing_cat.name}' — no expense transactions in DB."
                        )
                    )
                    continue

                # Pick from the richest category (cycling to spread the load)
                donor = covered_rich[rich_idx % len(covered_rich)]
                rich_idx += 1

                # Grab any single transaction from the donor category
                donor_tx = (
                    Transaction.objects.filter(category=donor, amount__lt=0)
                    .order_by("?")
                    .first()
                )
                if donor_tx:
                    donor_tx.category = missing_cat
                    subcats = subcat_map.get(missing_cat.id, [])
                    donor_tx.subcategory = random.choice(subcats) if subcats else None
                    donor_tx.categorization_source = Transaction.CategorizationSource.AI
                    steal_batch.append(donor_tx)
                    self.stdout.write(
                        f"    ✓ '{missing_cat.name}' ← stolen from '{donor.name}'"
                    )

            if steal_batch:
                Transaction.objects.bulk_update(
                    steal_batch, ["category", "subcategory", "categorization_source"]
                )

            # Also cover income categories
            for inc_cat in income_pool:
                has_tx = Transaction.objects.filter(
                    category=inc_cat, amount__gt=0
                ).exists()
                if not has_tx:
                    tx = Transaction.objects.filter(amount__gt=0).order_by("?").first()  # type: ignore[assignment]
                    if tx:
                        tx.category = inc_cat
                        subcats = subcat_map.get(inc_cat.id, [])
                        tx.subcategory = random.choice(subcats) if subcats else None
                        tx.categorization_source = Transaction.CategorizationSource.AI
                        tx.save(
                            update_fields=[
                                "category",
                                "subcategory",
                                "categorization_source",
                            ]
                        )
                        self.stdout.write(
                            f"    ✓ '{inc_cat.name}' — income transaction assigned"
                        )

            self.stdout.write(
                self.style.SUCCESS(f"  Phase 2 done — {len(steal_batch)} gaps filled.")
            )

        self.stdout.write(
            self.style.SUCCESS(
                "\n  All done. Reload /budget/ to see the data.\n"
                "  Use --all to re-shuffle everything.\n"
            )
        )
