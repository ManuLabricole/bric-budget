"""
transactions/management/_dev_guard.py — Helper for DEV ONLY management commands.

Used by commands that MUST NOT run in production :
  - dev_randomize_categories  — random tx categorization (dev seeding)
  - dev_seed_realistic        — 12 months of fake transactions
  - reset_seed                — wipes all seeded business data
  - reset_categories          — wipes all tx categorizations
  - recalculate_display_names — one-shot backfill (already executed in prod)

Pourquoi un guard centralisé :
    Une commande comme `reset_seed` lancée par erreur en prod détruit la base.
    Le guard refuse de tourner si DEBUG=False (= settings prod).
    On peut forcer via `--force-prod` pour les cas exceptionnels (migration data).
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import CommandError


def assert_dev_environment(command_name: str, allow_force: bool = True) -> None:
    """
    Raise CommandError if not running in DEBUG mode.

    Args:
        command_name : name of the calling command (for the error message).
        allow_force  : if True (default), advertise --force-prod in the error.

    Usage:
        class Command(BaseCommand):
            def handle(self, *args, **options):
                if not options.get("force_prod"):
                    assert_dev_environment("reset_seed")
                # ... destructive code ...
    """
    if settings.DEBUG:
        return

    hint = (
        " Pass --force-prod to override (rarely needed — only for planned data migrations)."
        if allow_force
        else ""
    )
    raise CommandError(
        f"`{command_name}` is a DEV ONLY command and refuses to run when DEBUG=False.{hint}"
    )


def add_force_prod_argument(parser) -> None:
    """
    Add the --force-prod CLI flag to a command's parser.

    Usage:
        def add_arguments(self, parser):
            add_force_prod_argument(parser)
    """
    parser.add_argument(
        "--force-prod",
        action="store_true",
        help="Override the DEV ONLY guard. Only use for planned data migrations.",
    )
