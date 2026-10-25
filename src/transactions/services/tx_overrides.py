"""
transactions/services/tx_overrides.py — sauvegarde/restauration de la couche manuelle (#346).

Corriger un parseur impose de purger puis réimporter un compte entier. Sans filet,
l'opération détruit tout ce que l'utilisateur a fait à la main. Mesuré sur un compte Yuh
réel de 481 transactions, d'après `categorization_source` :

    219 catégories posées par une RÈGLE    → se recréent seules au réimport
    181 catégories par DÉFAUT              → idem
     81 catégories MANUELLES               → perdues sans filet
     15 `nature` surchargées à la main     → perdues
    135 is_reconciled + 53 is_ignored      → perdus

Ce qui compte comme « manuel »
------------------------------
La catégorie n'est sauvegardée que si `categorization_source == MANUAL`. C'est la vérité
terrain que le modèle connaît déjà — inutile de la deviner en rejouant les règles, et
surtout il ne faut PAS réimposer une catégorie posée par une règle : au réimport les
règles tournent de nouveau, éventuellement améliorées depuis. Restaurer aveuglément
figerait un ancien verdict par-dessus un meilleur.

À l'inverse `is_reconciled`, `is_ignored`, `is_recurring` et `note` sont toujours
manuels : aucun import ne les produit.

`merchant_name` n'est sauvegardé que s'il DIFFÈRE de `display_name` : les connecteurs le
préremplissent avec le libellé nettoyé à l'import. Le sauvegarder systématiquement
réécrirait l'ancien libellé par-dessus celui du parseur corrigé — soit exactement
l'inverse du but recherché.

`is_internal_transfer` n'est volontairement PAS restauré : il est dérivé, à l'import, du
parseur (jambes de conversion) et de la catégorie « Virements ». Une valeur sauvegardée
serait périmée par construction ; le réimport la recalcule correctement.

Pourquoi pas `import_hash` comme clé
------------------------------------
Parce qu'il change dès qu'un parseur évolue — exactement la situation qui motive le
réimport. Vérifié sur Yuh : la rotation de la formule rend les 481 hashes inutilisables.

La clé repose donc sur les champs BRUTS, que le réimport reproduit à l'identique :

    (date, amount, currency, description_raw, occurrence)

`description_raw` et JAMAIS `display_name` : le nettoyage de libellé est souvent ce qu'on
vient de corriger. Mesuré sur Yuh : 474 clés distinctes pour 481 transactions (13 en
collision, pire cas 3) → unique à 481/481 une fois le rang d'occurrence ajouté.

Limite assumée du rang : attribué par `id` croissant des deux côtés, il suppose un ordre
d'import stable pour un groupe de lignes rigoureusement identiques. C'est le meilleur
proxy disponible sans identifiant bancaire, et dans ce cas les overrides du groupe sont
de toute façon presque toujours identiques.

Les catégories sont référencées par (slug, système/perso) et non par PK : une PK ne
survit pas à un reseed. Le drapeau « système » est indispensable — un slug système
(owner NULL, unique globalement) et un slug perso (unique par user) peuvent coexister,
et `for_user` renvoie les DEUX.
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

# Toujours manuels : aucun import ne les produit.
_FLAG_FIELDS = ("is_reconciled", "is_ignored", "is_recurring")
_MANUAL = Transaction.CategorizationSource.MANUAL


@dataclass
class ImportReport:
    """
    Résultat d'une restauration.

    `unmatched` et `unresolved` nomment les lignes concernées — jamais un simple compte :
    une restauration partielle qui ne dit pas CE qui manque ne vaut pas mieux qu'un échec
    silencieux.
    """

    applied: int = 0
    unmatched: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    category_restored: int = 0
    dry_run: bool = False

    @property
    def match_rate(self) -> float:
        total = self.applied + len(self.unmatched)
        return 1.0 if total == 0 else self.applied / total

    @property
    def is_clean(self) -> bool:
        return not self.unmatched and not self.unresolved


def _raw_key(tx: Transaction) -> tuple[str, str, str, str]:
    """Partie « champs bruts » de la clé, sans le rang d'occurrence."""
    return (
        tx.date.isoformat(),
        f"{Decimal(tx.amount):.2f}",
        tx.currency,
        tx.description_raw,
    )


def _ranked_keys(transactions: list[Transaction]) -> dict[tuple, Transaction]:
    """Clé complète (bruts + rang) → transaction. Rang par `id` croissant, déterministe."""
    seen: dict[tuple[str, str, str, str], int] = defaultdict(int)
    out: dict[tuple, Transaction] = {}
    for tx in sorted(transactions, key=lambda t: t.pk):
        raw = _raw_key(tx)
        out[(*raw, seen[raw])] = tx
        seen[raw] += 1
    return out


def _ref(obj) -> dict[str, Any] | None:
    """
    Référence sérialisable d'une Category/SubCategory : slug + système ou perso.

    Le drapeau n'est pas cosmétique : un slug système et un slug perso identiques
    coexistent légitimement (contraintes partielles, cf. Category.Meta.constraints) et
    `for_user` renvoie les deux. Sans lui, la résolution au retour en choisirait un au
    hasard.
    """
    if obj is None:
        return None
    return {"slug": obj.slug, "system": obj.owner_id is None}


def _manual_merchant_name(tx: Transaction) -> str:
    """Le nom marchand n'est « manuel » que s'il diffère du libellé nettoyé."""
    return tx.merchant_name if tx.merchant_name != tx.display_name else ""


def _override_for(tx: Transaction) -> dict[str, Any] | None:
    """Couche manuelle d'une transaction, ou None s'il n'y a rien à sauvegarder."""
    is_manual_cat = tx.categorization_source == _MANUAL
    flags = {f: getattr(tx, f) for f in _FLAG_FIELDS}
    merchant_name = _manual_merchant_name(tx)

    if not (is_manual_cat or any(flags.values()) or tx.note or merchant_name):
        return None

    return {
        # nature suit la catégorie : elle est préremplie depuis subcategory.default_nature
        # à la catégorisation, donc seule celle d'une catégorie manuelle est une surcharge.
        "category": _ref(tx.category) if is_manual_cat else None,
        "subcategory": _ref(tx.subcategory) if is_manual_cat else None,
        "nature": tx.nature if is_manual_cat else "",
        "note": tx.note,
        "merchant_name": merchant_name,
        **flags,
    }


def export_overrides(account) -> dict[str, Any]:
    """Sérialise la couche manuelle de `account`, prête à survivre à une purge."""
    transactions = list(
        Transaction.objects.filter(account=account).select_related(
            "category", "subcategory"
        )
    )
    overrides = []
    for key, tx in _ranked_keys(transactions).items():
        override = _override_for(tx)
        if override is None:
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
                **override,
            }
        )
    return {
        "version": OVERRIDE_FORMAT_VERSION,
        "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "account_id": account.pk,
        "account_name": account.name,
        "overrides": overrides,
    }


def _index(queryset) -> dict[tuple[str, bool], Any]:
    """Indexe par (slug, système) — deux homonymes système/perso ne s'écrasent plus."""
    return {(o.slug, o.owner_id is None): o for o in queryset}


def _resolve_refs(payload: dict, user) -> tuple[dict, dict]:
    """
    Résout les références de catégories en une passe — pas de requête par transaction.

    SCOPÉ `for_user`, et surtout PAS `unscoped()` : un slug n'est unique que par owner,
    donc une résolution globale pourrait rattacher les transactions à la catégorie
    PERSONNELLE d'un autre utilisateur (SR-001). `Category.objects` est fail-closed
    (OwnedManager, #213) : sans scope explicite le filtre renvoie `.none()` et les
    overrides seraient restaurés sans catégorie, en silence.
    """
    cat_slugs = {o["category"]["slug"] for o in payload["overrides"] if o["category"]}
    sub_slugs = {
        o["subcategory"]["slug"] for o in payload["overrides"] if o["subcategory"]
    }
    return (
        _index(Category.objects.for_user(user).filter(slug__in=cat_slugs)),
        _index(SubCategory.objects.for_user(user).filter(slug__in=sub_slugs)),
    )


def _describe(key: dict) -> str:
    return (
        f"{key['date']} {key['amount']} {key['currency']} — {key['description_raw']}"
        f" (occurrence {key['occurrence']})"
    )


def import_overrides(payload: dict, *, user, dry_run: bool = False) -> ImportReport:
    """
    Réapplique la couche manuelle.

    `user` est obligatoire : il scope la résolution des catégories (cf. _resolve_refs).

    Les transactions sans override sont laissées strictement intactes — le correctif d'un
    parseur crée des lignes légitimement nouvelles (jambes de conversion manquantes) qu'il
    ne faut surtout pas toucher. Une référence de catégorie introuvable (supprimée,
    renommée) est SIGNALÉE et la transaction laissée telle quelle : on ne vide jamais un
    champ faute d'avoir su le résoudre.
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
    categories, subcategories = _resolve_refs(payload, user)
    to_update: list[Transaction] = []
    fields = {"note", "merchant_name", *_FLAG_FIELDS}

    for override in payload["overrides"]:
        key = override["key"]
        tx = by_key.get(
            (
                key["date"],
                key["amount"],
                key["currency"],
                key["description_raw"],
                key["occurrence"],
            )
        )
        if tx is None:
            report.unmatched.append(_describe(key))
            continue

        for f in _FLAG_FIELDS:
            setattr(tx, f, override[f])
        if override["note"]:
            tx.note = override["note"]
        if override["merchant_name"]:
            tx.merchant_name = override["merchant_name"]

        if override["category"]:
            ref = override["category"]
            category = categories.get((ref["slug"], ref["system"]))
            if category is None:
                report.unresolved.append(
                    f"{_describe(key)} → catégorie « {ref['slug']} » introuvable"
                )
            else:
                sub = None
                sref = override["subcategory"]
                if sref:
                    sub = subcategories.get((sref["slug"], sref["system"]))
                    if sub is None:
                        report.unresolved.append(
                            f"{_describe(key)} → sous-catégorie « {sref['slug']} » introuvable"
                        )
                tx.category = category
                # Ne pas écraser une sous-catégorie fraîchement posée par une règle avec
                # None faute d'avoir su résoudre la référence sauvegardée.
                if sub is not None or sref is None:
                    tx.subcategory = sub
                tx.nature = override["nature"]
                # La provenance suit la catégorie, sinon la ligne resterait marquée
                # « rule » en pointant une règle qui ne l'a pas produite.
                tx.categorization_source = _MANUAL
                tx.categorization_rule = None
                report.category_restored += 1
                fields |= {
                    "category",
                    "subcategory",
                    "nature",
                    "categorization_source",
                    "categorization_rule",
                }

        to_update.append(tx)
        report.applied += 1

    if not dry_run and to_update:
        with db_transaction.atomic():
            Transaction.objects.bulk_update(to_update, sorted(fields), batch_size=500)
    return report
