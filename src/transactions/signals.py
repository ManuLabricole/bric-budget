"""
transactions/signals.py — Pre-delete cleanup for ImportLog.

Pourquoi pre_delete et pas post_delete ?
-----------------------------------------
Transaction.import_log est une FK nullable (null=True). Dans le Collector Django,
les FK nullables ne créent PAS de dépendance de tri. Résultat : ImportLog est supprimé
EN PREMIER (ordre d'insertion dans le Collector), son post_delete fire, mais les
transactions en cascade ne sont PAS encore supprimées à ce moment.

En utilisant pre_delete :
  - Toutes les transactions existent encore en DB
  - On peut vérifier si D'AUTRES imports couvrent la même date
  - On identifie correctement les snapshots orphelins AVANT la suppression

Séquence d'exécution :
  1. pre_delete signal (ici) → identifier les snapshots orphelins → les supprimer
  2. ImportLog.delete() → fast_delete des transactions (nullable FK → fast_deletes)
  3. SQL DELETE ImportLog

Pourquoi un signal et pas une FK CASCADE vers BalanceSnapshot ?
----------------------------------------------------------------
Un BalanceSnapshot est lié à un (account, date) — une seule entrée par jour.
Deux imports qui se chevauchent sur la même date partagent le même snapshot.
Une FK CASCADE supprimerait le snapshot dès que le premier import est supprimé,
même si l'autre import couvre encore cette date.

La solution correcte : avant suppression d'un ImportLog, supprimer les
BalanceSnapshots pour lesquels IL N'EXISTERA PLUS AUCUNE transaction (ni de cet
import, ni d'un autre) après la suppression.
"""

import logging

from django.db.models import Q
from django.db.models.signals import pre_delete

from transactions.models import ImportLog

logger = logging.getLogger(__name__)


def cleanup_orphaned_snapshots(sender, instance, **kwargs):
    """
    Supprime les BalanceSnapshots qui vont devenir orphelins suite à la suppression
    de cet ImportLog.

    Appelé en PRE_DELETE : à ce stade, toutes les transactions existent encore,
    ce qui permet de distinguer "orphelin après suppression" vs "couvert par un autre import".

    "Orphelin après suppression" = aucune autre transaction (autre import ou manuelle)
    n'existe pour ce (account, date).
    """
    from accounts.models import BalanceSnapshot
    from transactions.models import Transaction

    account = instance.account
    date_min = instance.date_min
    date_max = instance.date_max

    # Si l'import n'avait pas de transactions (0 créées), rien à nettoyer
    if date_min is None or date_max is None:
        return

    # Dates couvertes PAR CET import (transactions qui vont être supprimées)
    dates_in_this_import = set(
        Transaction.objects.filter(import_log=instance).values_list("date", flat=True)
    )

    if not dates_in_this_import:
        return

    # Dates qui auront encore des transactions APRÈS suppression de cet import.
    # Inclut : transactions d'autres imports ET transactions manuelles (import_log=NULL).
    # Q(import_log__isnull=True) | ~Q(import_log=instance) car exclude() ne remonte
    # pas les NULL en PostgreSQL pour les FK nullables.
    surviving_tx_dates = set(
        Transaction.objects.filter(
            account=account,
            date__in=dates_in_this_import,
        )
        .filter(Q(import_log__isnull=True) | ~Q(import_log=instance))
        .values_list("date", flat=True)
    )

    # Snapshots orphelins = couverts par cet import mais sans autre transaction restante
    orphaned_dates = dates_in_this_import - surviving_tx_dates

    if not orphaned_dates:
        return

    count, _ = BalanceSnapshot.objects.filter(
        account=account,
        date__in=orphaned_dates,
    ).delete()

    if count:
        logger.info(
            "[signal] %d BalanceSnapshot(s) orphelin(s) supprimé(s) pour %s",
            count,
            account,
        )


# weak=False : évite que la weakref soit collectée dans les environnements de test.
# dispatch_uid : garantit un seul enregistrement même si signals.py est importé plusieurs fois.
pre_delete.connect(
    cleanup_orphaned_snapshots,
    sender=ImportLog,
    weak=False,
    dispatch_uid="transactions.signals.cleanup_orphaned_snapshots",
)
