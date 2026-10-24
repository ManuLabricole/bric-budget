"""
transactions/services/tx_overrides.py — sauvegarde/restauration de la couche manuelle (#346).

Corriger un parseur impose souvent de purger puis réimporter un compte entier. Sans
filet, l'opération détruit tout ce que l'utilisateur a fait à la main : catégories
posées sans règle, transactions pointées, transactions ignorées, notes. Mesuré sur un
compte Yuh réel de 481 transactions — 113 règles actives rejouées :

    221 catégories  reproduites par une règle      → rien à sauver
    141 "Inconnu" + 40 "Revenus"                   → défauts d'import, rien à sauver
     64 catégories posées à la main sans règle     → PERDUES
    135 is_reconciled + 53 is_ignored              → PERDUS

Pourquoi pas `import_hash` comme clé
------------------------------------
Parce qu'il change dès qu'un parseur évolue — et c'est exactement la situation qui
motive le réimport. Vérifié sur Yuh : la rotation de la formule de hash rend les 481
hashes existants inutilisables.

La clé repose donc sur les champs BRUTS, que le réimport reproduit à l'identique :

    (date, amount, currency, description_raw, occurrence)

`description_raw` et JAMAIS `display_name` : le nettoyage de libellé est justement ce
qu'on vient souvent de corriger. `occurrence` est un rang parmi les lignes strictement
identiques — même nécessité que l'`occurrence_index` des parseurs. Mesuré sur Yuh :
474 clés distinctes pour 481 transactions (13 en collision, pire cas 3) → unique à
481/481 une fois le rang ajouté.

Limite assumée du rang : il est attribué par `id` croissant des deux côtés. Pour un
groupe de lignes rigoureusement identiques, l'ordre d'import est donc supposé stable.
C'est le meilleur proxy disponible sans identifiant bancaire, et dans ce cas de figure
les overrides du groupe sont de toute façon presque toujours identiques.

Les catégories sont référencées par SLUG, pas par PK : une PK n'a aucune raison de
survivre à un reseed de la base de référence.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.db import transaction as db_transaction

from transactions.models import Category, SubCategory, Transaction

OVERRIDE_FORMAT_VERSION = 1

# Champs constituant la « couche manuelle » : tout ce qu'un réimport ne sait pas
# reconstruire seul. `category` est inclus même si les règles en réassignent une
# partie — le rapport distingue ensuite restauré / déjà correct.
_FLAG_FIELDS = ("is_reconciled", "is_ignored", "is_recurring")
_TEXT_FIELDS = ("note", "merchant_name")


@dataclass
class ImportReport:
    """Résultat d'une restauration. `unmatched` nomme les lignes, jamais un simple compte."""

    applied: int = 0
    unmatched: list[str] = field(default_factory=list)
    category_already_correct: int = 0
    category_changed: int = 0
    dry_run: bool = False

    @property
    def match_rate(self) -> float:
        total = self.applied + len(self.unmatched)
        return 1.0 if total == 0 else self.applied / total


def _raw_key(tx: Transaction) -> tuple[str, str, str, str]:
    """Partie « champs bruts » de la clé, sans le rang d'occurrence."""
    return (
        tx.date.isoformat(),
        f"{Decimal(tx.amount):.2f}",
        tx.currency,
        tx.description_raw,
    )


def _ranked_keys(transactions: list[Transaction]) -> dict[tuple, Transaction]:
    """
    Associe à chaque transaction sa clé complète (bruts + rang). Le rang est attribué
    par `id` croissant pour être déterministe des deux côtés de l'aller-retour.
    """
    seen: dict[tuple[str, str, str, str], int] = defaultdict(int)
    out: dict[tuple, Transaction] = {}
    for tx in sorted(transactions, key=lambda t: t.pk):
        raw = _raw_key(tx)
        out[(*raw, seen[raw])] = tx
        seen[raw] += 1
    return out


def _has_manual_layer(tx: Transaction) -> bool:
    """Une transaction sans rien de manuel n'a pas besoin d'être exportée."""
    return bool(
        tx.category_id
        or any(getattr(tx, f) for f in _FLAG_FIELDS)
        or any(getattr(tx, f) for f in _TEXT_FIELDS)
    )


def export_overrides(account) -> dict[str, Any]:
    """Sérialise la couche manuelle de `account`, prête à survivre à une purge."""
    transactions = list(
        Transaction.objects.filter(account=account).select_related(
            "category", "subcategory"
        )
    )
    overrides = []
    for key, tx in _ranked_keys(transactions).items():
        if not _has_manual_layer(tx):
            continue
        date_iso, amount, currency, description_raw, occurrence = key
        overrides.append(
            {
                "key": {
                    "date": date_iso,
                    "amount": amount,
                    "currency": currency,
                    "description_raw": description_raw,
                    "occurrence": occurrence,
                },
                "category": tx.category.slug if tx.category else None,
                "subcategory": tx.subcategory.slug if tx.subcategory else None,
                **{f: getattr(tx, f) for f in _FLAG_FIELDS},
                **{f: getattr(tx, f) for f in _TEXT_FIELDS},
            }
        )
    return {
        "version": OVERRIDE_FORMAT_VERSION,
        "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "account_id": account.pk,
        "account_name": account.name,
        "overrides": overrides,
    }


def _resolve_categories(
    payload: dict, user
) -> tuple[dict[str, Category], dict[str, SubCategory]]:
    """
    Résout les slugs en une passe — pas de requête par transaction.

    SCOPÉ `for_user`, et surtout PAS `unscoped()` : un slug de catégorie n'est unique
    que par owner, donc une restauration non scopée pourrait rattacher les transactions
    à la catégorie PERSONNELLE d'un autre utilisateur (SR-001). `Category.objects` est
    fail-closed (OwnedManager, #213) : sans scope explicite le filtre renvoie `.none()`
    et les overrides seraient restaurés sans catégorie, en silence — c'est exactement
    ce que le manager a attrapé pendant l'écriture de ce module.
    """
    cat_slugs = {o["category"] for o in payload["overrides"] if o.get("category")}
    sub_slugs = {o["subcategory"] for o in payload["overrides"] if o.get("subcategory")}
    return (
        {c.slug: c for c in Category.objects.for_user(user).filter(slug__in=cat_slugs)},
        {
            s.slug: s
            for s in SubCategory.objects.for_user(user).filter(slug__in=sub_slugs)
        },
    )


def import_overrides(payload: dict, *, user, dry_run: bool = False) -> ImportReport:
    """
    `user` est obligatoire : il scope la résolution des catégories (voir
    _resolve_categories). Réapplique la couche manuelle. Les transactions sans override sont laissées
    strictement intactes — le correctif d'un parseur crée des lignes légitimement
    nouvelles (jambes de conversion manquantes) qu'il ne faut surtout pas toucher.
    """
    version = payload.get("version")
    if version != OVERRIDE_FORMAT_VERSION:
        raise ValueError(
            f"Format d'overrides v{version} non supporté (attendu v{OVERRIDE_FORMAT_VERSION})."
        )

    report = ImportReport(dry_run=dry_run)
    by_key = _ranked_keys(
        list(Transaction.objects.filter(account_id=payload["account_id"]))
    )
    categories, subcategories = _resolve_categories(payload, user)
    to_update: list[Transaction] = []

    for override in payload["overrides"]:
        k = override["key"]
        key = (
            k["date"],
            k["amount"],
            k["currency"],
            k["description_raw"],
            k["occurrence"],
        )
        tx = by_key.get(key)
        if tx is None:
            report.unmatched.append(
                f"{k['date']} {k['amount']} {k['currency']} — {k['description_raw']}"
                f" (occurrence {k['occurrence']})"
            )
            continue

        category = (
            categories.get(override["category"]) if override["category"] else None
        )
        if category is not None:
            if tx.category_id == category.pk:
                report.category_already_correct += 1
            else:
                report.category_changed += 1
            tx.category = category
        subcategory_slug = override.get("subcategory")
        if subcategory_slug:
            tx.subcategory = subcategories.get(subcategory_slug)
        for f in (*_FLAG_FIELDS, *_TEXT_FIELDS):
            setattr(tx, f, override[f])

        to_update.append(tx)
        report.applied += 1

    if not dry_run and to_update:
        with db_transaction.atomic():
            Transaction.objects.bulk_update(
                to_update,
                ["category", "subcategory", *_FLAG_FIELDS, *_TEXT_FIELDS],
                batch_size=500,
            )
    return report
