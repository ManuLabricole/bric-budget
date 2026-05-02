"""
transactions/management/commands/seed_categories.py

Crée ou met à jour uniquement les Categories et SubCategories depuis categories.json.
Ne touche pas aux banques ni aux comptes.

Usage :
    python manage.py seed_categories
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from transactions.models import Category, SubCategory


class Command(BaseCommand):
    help = "Crée ou met à jour les catégories depuis categories.json."

    def handle(self, *args, **options):
        json_path = (
            Path(settings.BASE_DIR).parent
            / "assets"
            / "private"
            / "references"
            / "categories"
            / "categories.json"
        )

        if not json_path.exists():
            self.stdout.write(self.style.ERROR(f"Fichier introuvable : {json_path}"))
            return

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        cat_created = cat_updated = sub_created = sub_updated = 0

        for cat_data in data["categories"]:
            category, created = Category.objects.update_or_create(
                slug=cat_data["slug"],
                defaults={
                    "name": cat_data["name"],
                    "icon": cat_data.get("icon", ""),
                    "colour_hex": cat_data.get("colour_hex", ""),
                    "order": cat_data.get("order", 0),
                    "is_system": cat_data.get("is_system", False),
                },
            )
            if created:
                cat_created += 1
            else:
                cat_updated += 1

            for sub_data in cat_data.get("subcategories", []):
                default_nature = sub_data.get("default_nature", "")
                if default_nature == "neutral":
                    default_nature = ""
                _, sub_c = SubCategory.objects.update_or_create(
                    slug=sub_data["slug"],
                    defaults={
                        "category": category,
                        "name": sub_data["name"],
                        "default_nature": default_nature,
                        "is_system": sub_data.get("is_system", False),
                    },
                )
                if sub_c:
                    sub_created += 1
                else:
                    sub_updated += 1

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
