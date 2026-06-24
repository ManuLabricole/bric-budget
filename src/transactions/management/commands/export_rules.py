"""
transactions/management/commands/export_rules.py

Exporte toutes les CategorizationRule (actives ET inactives) vers un fichier JSON.

Pourquoi cette commande existe :
    La session de classification manuelle (Phase 2G) va créer des dizaines de règles.
    Si la DB est corrompue ou resetée, tout ce travail est perdu.
    Cette commande produit un backup lisible + réimportable avant de commencer.

Usage :
    python src/manage.py export_rules                      # stdout (JSON brut)
    python src/manage.py export_rules --output rules.json  # fichier
    make export-rules                                      # → assets/private/rules_backup_YYYYMMDD.json

Format de sortie :
    {
        "exported_at": "2026-05-02",
        "count": 42,
        "rules": [
            {
                "keyword": "MIGROS",
                "category_slug": "alimentation",
                "subcategory_slug": "supermarche",
                "target_field": "description_raw",
                "priority": 10,
                "is_active": true
            },
            ...
        ]
    }
"""

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from transactions.models import CategorizationRule


class Command(BaseCommand):
    help = (
        "Export toutes les CategorizationRule vers JSON (backup avant classification)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=None,
            help="Chemin du fichier de sortie. Si absent, écrit sur stdout.",
        )

    def handle(self, *args, **options):
        # Charger toutes les règles actives, triées par priorité puis keyword.
        # .values() retourne un queryset de dicts plats — pas d'objets ORM.
        # Les champs FK (category, subcategory) sont traversés avec __ pour obtenir
        # le slug (clé métier stable) plutôt que l'ID (clé technique instable).
        # #213 : export CLI global (admin) → unscoped() (auditable par grep).
        rules_qs = (
            CategorizationRule.objects.unscoped()
            .values(
                "keyword",
                "category__slug",
                "subcategory__slug",
                "target_field",
                "priority",
                "is_active",
            )
            .order_by("priority", "keyword")
        )

        # Renommer les clés de traversée (__) en clés lisibles (_slug suffix)
        rules = [
            {
                "keyword": r["keyword"],
                "category_slug": r["category__slug"],
                "subcategory_slug": r["subcategory__slug"],
                "target_field": r["target_field"],
                "priority": r["priority"],
                "is_active": r["is_active"],
            }
            for r in rules_qs
        ]

        data = {
            "exported_at": str(date.today()),
            "count": len(rules),
            "rules": rules,
        }

        output_json = json.dumps(data, indent=2, ensure_ascii=False)

        output_path = options.get("output")
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(output_json, encoding="utf-8")
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(rules)} règle(s) exportée(s) → {path.resolve()}"
                )
            )
        else:
            # Écrire directement sur stdout — utile pour piping ou vérification rapide
            self.stdout.write(output_json)
