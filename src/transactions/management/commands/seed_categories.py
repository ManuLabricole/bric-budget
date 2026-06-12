"""
transactions/management/commands/seed_categories.py

Synchronise Categories et SubCategories depuis le référentiel committé
src/transactions/reference/categories.json (#126). Idempotent (update_or_create) :
tournée N fois, elle n'applique que le delta. Lancée à chaque deploy via
sync_reference_data — un échec doit être BRUYANT (CommandError → exit ≠ 0),
jamais un return silencieux.

Usage :
    python manage.py seed_categories [--dry-run]
"""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from transactions.models import Category, SubCategory

logger = logging.getLogger(__name__)


def reference_json_path() -> Path:
    """Seam de test — le référentiel committé DANS l'app propriétaire (Two Scoops)."""
    return Path(settings.BASE_DIR) / "transactions" / "reference" / "categories.json"


class Command(BaseCommand):
    help = "Synchronise les catégories depuis reference/categories.json (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait synchronisé, n'écrit rien.",
        )

    def handle(self, *args, **options):
        json_path = reference_json_path()
        if not json_path.exists():
            # ⛔ Le release deploy doit VOIR l'échec : exit ≠ 0, pas de message poli.
            raise CommandError(f"Référentiel introuvable : {json_path}")

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        categories = data["categories"]
        sub_total = sum(len(c.get("subcategories", [])) for c in categories)

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {len(categories)} catégories / {sub_total} sous-catégories "
                "seraient synchronisées — rien n'a été écrit."
            )
            return

        cat_created = cat_updated = sub_created = sub_updated = 0

        # SR-003 : un déploiement interrompu ne doit jamais laisser un référentiel
        # à moitié écrit — tout ou rien.
        with transaction.atomic():
            for cat_data in categories:
                category, created = Category.objects.update_or_create(
                    slug=cat_data["slug"],
                    defaults={
                        "name": cat_data["name"],
                        "icon": cat_data.get("icon", ""),
                        "colour_hex": cat_data.get("colour_hex", ""),
                        "order": cat_data.get("order", 0),
                        "is_system": cat_data.get("is_system", False),
                        # Zéro drift : désactiver une catégorie dans le référentiel
                        # la désactive en DB au deploy suivant.
                        "is_active": cat_data.get("is_active", True),
                    },
                )
                if created:
                    cat_created += 1
                else:
                    cat_updated += 1

                for sub_data in cat_data.get("subcategories", []):
                    default_nature = sub_data.get("default_nature", "")
                    # Compat JSON historique : "neutral" n'est pas un choix du modèle.
                    if default_nature == "neutral":
                        default_nature = ""
                    _, sub_c = SubCategory.objects.update_or_create(
                        slug=sub_data["slug"],
                        defaults={
                            "category": category,
                            "name": sub_data["name"],
                            "icon": sub_data.get("icon", ""),
                            "default_nature": default_nature,
                            "is_system": sub_data.get("is_system", False),
                            "is_active": sub_data.get("is_active", True),
                        },
                    )
                    if sub_c:
                        sub_created += 1
                    else:
                        sub_updated += 1

        logger.info(
            "seed_categories ok cat_created=%s cat_updated=%s sub_created=%s sub_updated=%s",
            cat_created,
            cat_updated,
            sub_created,
            sub_updated,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"✓  {cat_created} catégories créées, {cat_updated} mises à jour"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"✓  {sub_created} sous-catégories créées, {sub_updated} mises à jour"
            )
        )
