"""
transactions/management/commands/backfill_chf.py — rattrape les conversions CHF
manquantes (#118).

SAFE + IDEMPOTENT : ne fait QUE remplir des champs CHF restés NULL avec la valeur
convertie correcte. Pas de dev-guard (contrairement aux commandes `dev_*`
destructives) — c'est une maintenance corrective pensée AUSSI pour la prod, après
déploiement du fix de conversion. Rejouable sans effet de bord.

Recalcule :
    Transaction.amount_chf      (devise ≠ CHF, NULL → montant × taux)
    BalanceSnapshot.balance_chf (devise ≠ CHF, solde présent mais CHF NULL)

Deux causes de trous rattrapées :
  1. API de taux indisponible à l'import → champ laissé None (best effort).
  2. Avant #118, le SOLDE des snapshots n'était jamais converti (seul amount_chf
     l'était) → comptes EUR affichés « — » / « conversion en attente » en patrimoine.

Usage :
    python manage.py backfill_chf
    python manage.py backfill_chf --dry-run   # compte les candidats, n'écrit rien
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import QuerySet

from accounts.models import BalanceSnapshot
from services.exchange_rates import to_chf
from transactions.models import Transaction

BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Recalcule les amount_chf / balance_chf manquants (conversion CHF, #118)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compter les candidats sans rien écrire (aucun appel réseau).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Devise ≠ CHF uniquement : pour un compte CHF, amount_chf / balance_chf
        # valent déjà la valeur locale (peuplés à l'import). On écarte aussi la
        # devise vide (compte sans devise connue → conversion impossible).
        tx_qs = (
            Transaction.objects.filter(amount_chf__isnull=True)
            .exclude(currency="CHF")
            .exclude(currency="")
        )
        snap_qs = (
            BalanceSnapshot.objects.filter(
                balance__isnull=False, balance_chf__isnull=True
            )
            .exclude(currency="CHF")
            .exclude(currency="")
        )

        if dry_run:
            self.stdout.write(
                f"[dry-run] Transactions amount_chf NULL (non-CHF) : {tx_qs.count()}"
            )
            self.stdout.write(
                f"[dry-run] Snapshots balance_chf NULL (non-CHF) : {snap_qs.count()}"
            )
            return

        tx_updated, tx_no_rate = self._backfill(
            tx_qs, value_attr="amount", target_attr="amount_chf"
        )
        snap_updated, snap_no_rate = self._backfill(
            snap_qs, value_attr="balance", target_attr="balance_chf"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"amount_chf : {tx_updated} backfillés ({tx_no_rate} sans taux) — "
                f"balance_chf : {snap_updated} backfillés ({snap_no_rate} sans taux)"
            )
        )

    def _backfill(
        self, qs: QuerySet, *, value_attr: str, target_attr: str
    ) -> tuple[int, int]:
        """Convertit value_attr → target_attr (CHF) pour chaque objet du queryset.

        Retourne (updated, no_rate). Seuls les objets dont la conversion réussit
        (taux dispo) sont mis à jour → idempotent et rejouable. bulk_update par
        lots pour éviter une requête par ligne sur un gros backfill.
        """
        model = qs.model
        updated = 0
        no_rate = 0
        batch: list = []
        for obj in qs.iterator(chunk_size=BATCH_SIZE):
            chf = to_chf(getattr(obj, value_attr), obj.currency, obj.date)
            if chf is None:
                no_rate += 1
                continue
            setattr(obj, target_attr, chf)
            batch.append(obj)
            updated += 1
            if len(batch) >= BATCH_SIZE:
                model.objects.bulk_update(batch, [target_attr])
                batch.clear()
        if batch:
            model.objects.bulk_update(batch, [target_attr])
        return updated, no_rate
