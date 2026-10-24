"""
transactions/management/commands/export_tx_overrides.py — filet avant purge (#346).

Sauvegarde la couche manuelle d'un compte (catégories posées à la main, transactions
pointées, ignorées, notes) dans un JSON, pour la restaurer après une purge + réimport.

À lancer AVANT toute purge. La logique vit dans services/tx_overrides.py — cette
commande n'est qu'une porte CLI.

Usage :
    python manage.py export_tx_overrides --account 226 --output /tmp/yuh_overrides.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account
from transactions.services import tx_overrides


class Command(BaseCommand):
    help = "Exporte la couche manuelle (catégories, flags, notes) d'un compte en JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "--account", type=int, required=True, help="ID du compte à exporter"
        )
        parser.add_argument(
            "--output", required=True, help="Chemin du fichier JSON à écrire"
        )

    def handle(self, *args, **options):
        # Accès non scopé assumé : commande d'ops lancée en CLI par un admin, hors
        # cycle requête, donc sans request.user sur qui scoper. `Account.objects`
        # n'est pas fail-closed (manager classique) — contrairement à Category, dont
        # la résolution EST scopée côté service (cf. _resolve_categories).
        account = Account.objects.filter(pk=options["account"]).first()
        if account is None:
            raise CommandError(f"Compte {options['account']} introuvable.")

        payload = tx_overrides.export_overrides(account)
        out = Path(options["output"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        n = len(payload["overrides"])
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ {n} override(s) exporté(s) depuis « {account.name} » → {out}"
            )
        )
        if n == 0:
            self.stdout.write(
                self.style.WARNING(
                    "   Aucune couche manuelle sur ce compte — rien à restaurer."
                )
            )
