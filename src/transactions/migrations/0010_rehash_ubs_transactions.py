"""
transactions/migrations/0010_rehash_ubs_transactions.py

Recalcule import_hash pour toutes les transactions UBS.

Contexte :
    L'ancienne formule n'utilisait pas l'identifiant unique bancaire :
        sha256(f"{date}|{time}|{amount}|{description1}|{description2}")

    Cette formule est fragile : si UBS modifie un caractère dans la description
    lors d'un re-export (ex: padding variable, encodage), le hash change et la
    transaction est réimportée en double.

    UBS assigne un "No de transaction" globalement unique par ligne (ex: "9999125BN1308361").
    C'est l'identifiant parfait : stable entre exports, garanti unique par la banque.

Nouvelle formule :
    sha256(f"ubs_tx|{no_transaction}")

    no_transaction extrait de description_raw : "... | No de transaction: XXXXXXXXX"
    Si absent (transactions très anciennes sans description3) → fallback formule précédente.

Déroulement :
    1. Extraire no_transaction depuis description_raw pour chaque transaction UBS
    2. Calculer le nouveau hash
    3. Détecter les doublons éventuels → garder le plus ancien (pk le plus bas)
    4. Mettre à jour import_hash

Idempotente : à la 2ème passe, le hash recalculé = hash déjà stocké → update sans effet.
"""

import hashlib
import re

from django.db import migrations

_NO_TX_RE = re.compile(r"No de transaction:\s*(\S+)", re.IGNORECASE)


def rehash_ubs_transactions(apps, schema_editor):
    Transaction = apps.get_model("transactions", "Transaction")

    ubs_transactions = list(
        Transaction.objects.filter(account__bank__slug="ubs")
        .select_related("account")
        .order_by("pk")
    )

    if not ubs_transactions:
        return

    new_hashes = {}  # pk → new_hash
    fallback_count = 0

    for tx in ubs_transactions:
        m = _NO_TX_RE.search(tx.description_raw or "")
        if m:
            no_transaction = m.group(1).strip()
            raw = f"ubs_tx|{no_transaction}"
        else:
            # Fallback : formule précédente (date|time|amount|desc)
            # description_raw = "desc1 | desc2 | desc3" → on réextrait desc1 et desc2
            parts = [p.strip() for p in (tx.description_raw or "").split(" | ")]
            description1 = parts[0] if len(parts) > 0 else ""
            description2 = parts[1] if len(parts) > 1 else ""
            time_str = str(tx.time) if tx.time else ""
            raw = f"{tx.date}|{time_str}|{tx.amount}|{description1}|{description2}"
            fallback_count += 1

        new_hashes[tx.pk] = hashlib.sha256(raw.encode()).hexdigest()

    if fallback_count:
        print(
            f"  [migration] {fallback_count} transactions UBS sans No de transaction (fallback formule précédente)"
        )

    # Détecter les doublons → garder le plus ancien (pk le plus bas)
    seen_hashes = {}
    pks_to_delete = []

    for tx in ubs_transactions:
        nh = new_hashes[tx.pk]
        if nh in seen_hashes:
            pks_to_delete.append(tx.pk)
        else:
            seen_hashes[nh] = tx.pk

    if pks_to_delete:
        deleted_count = Transaction.objects.filter(pk__in=pks_to_delete).delete()[0]
        print(
            f"  [migration] Suppression de {deleted_count} transactions UBS en double"
        )

    pks_to_update = [pk for pk in new_hashes if pk not in pks_to_delete]
    for pk in pks_to_update:
        Transaction.objects.filter(pk=pk).update(import_hash=new_hashes[pk])

    print(
        f"  [migration] {len(pks_to_update)} transactions UBS re-hashées (nouvelle formule No de transaction)"
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("transactions", "0009_rehash_cic_transactions"),
    ]

    operations = [
        migrations.RunPython(rehash_ubs_transactions, reverse_code=noop),
    ]
