"""
transactions/management/commands/import_tx_overrides.py — restauration après réimport (#346).

Réapplique la couche manuelle sauvegardée par `export_tx_overrides`. Les transactions
sans override sont laissées strictement intactes : un correctif de parseur crée des
lignes légitimement nouvelles (jambes de conversion manquantes) qu'il ne faut pas toucher.

⛔ Toujours passer par `--dry-run` AVANT de purger : il annonce le taux de réappariement
sur les données en place. S'il n'est pas de 100 %, ne pas purger.

Usage :
    python manage.py import_tx_overrides --input /tmp/yuh_overrides.json --dry-run
    python manage.py import_tx_overrides --input /tmp/yuh_overrides.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account
from transactions.services import tx_overrides


class Command(BaseCommand):
    help = "Restaure la couche manuelle d'un compte depuis un JSON d'overrides"

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True, help="JSON produit par l'export")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Annonce le résultat sans rien écrire",
        )

    def handle(self, *args, **options):
        path = Path(options["input"])
        if not path.exists():
            raise CommandError(f"Fichier introuvable : {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))

        account = Account.objects.filter(pk=payload["account_id"]).first()
        if account is None:
            raise CommandError(
                f"Compte {payload['account_id']} introuvable — l'export vient-il de cette base ?"
            )
        # La résolution des catégories est scopée sur le propriétaire du compte : un
        # slug n'est unique que par owner (cf. services/tx_overrides._resolve_categories).
        user = account.members.first()
        if user is None:
            raise CommandError(f"Le compte « {account.name} » n'a aucun membre.")

        report = tx_overrides.import_overrides(
            payload, user=user, dry_run=options["dry_run"]
        )

        prefix = "[dry-run] " if report.dry_run else ""
        self.stdout.write(
            f"{prefix}{report.applied} override(s) appliqué(s) sur « {account.name} »"
        )
        self.stdout.write(
            f"{prefix}  dont catégories manuelles restaurées : {report.category_restored}"
        )

        if report.is_clean:
            self.stdout.write(
                self.style.SUCCESS(f"{prefix}✅ réappariement 100 % — purge sûre.")
            )
            return

        # Liste EXHAUSTIVE, jamais tronquée : l'opérateur doit pouvoir identifier chaque
        # ligne perdue pour décider s'il purge. Un « … et 37 autres » rendrait le filet
        # inutilisable précisément quand il sert le plus.
        if report.unmatched:
            self.stdout.write(
                self.style.ERROR(
                    f"{prefix}⛔ {len(report.unmatched)} override(s) NON réapparié(s)"
                    f" — taux {report.match_rate:.1%}. Ne pas purger en l'état."
                )
            )
            for line in report.unmatched:
                self.stdout.write(f"     {line}")

        if report.unresolved:
            self.stdout.write(
                self.style.ERROR(
                    f"{prefix}⛔ {len(report.unresolved)} référence(s) de catégorie"
                    " introuvable(s) — champ laissé en l'état, pas vidé :"
                )
            )
            for line in report.unresolved:
                self.stdout.write(f"     {line}")
