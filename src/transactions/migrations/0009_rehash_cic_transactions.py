"""
transactions/migrations/0009_rehash_cic_transactions.py

Recalcule import_hash pour toutes les transactions CIC.

Contexte :
    L'ancienne formule incluait row_idx (position de la ligne dans l'Excel CIC) :
        sha256(f"{rib}|{row_idx}|{date}|{amount}|{description}")

    CIC exporte en ordre antichronologique (plus récentes en haut).
    Quand un nouveau relevé est exporté, les transactions existantes décalent d'autant
    de lignes que de nouvelles transactions → row_idx change → hash change → elles sont
    réimportées comme nouvelles au lieu d'être détectées comme doublons.

Nouvelle formule (stable entre exports) :
    sha256(f"{rib}|{date}|{amount}|{description}")

    rib = Account.contract_number (identique à ce que le parser extrait du fichier)

Déroulement :
    1. Calculer le nouveau hash pour chaque transaction CIC
    2. Détecter les doublons introduits par la correction (même nouveau hash)
       → garder la transaction la plus ancienne (pk le plus bas), supprimer les autres
    3. Mettre à jour import_hash pour les transactions conservées

Idempotente : si exécutée deux fois, le hash calculé à la 2ème passe sera identique
à celui déjà stocké → update sans effet de bord.
"""

import hashlib

from django.db import migrations


def rehash_cic_transactions(apps, schema_editor):
    Transaction = apps.get_model("transactions", "Transaction")

    cic_transactions = list(
        Transaction.objects.filter(account__bank__slug="cic")
        .select_related("account")
        .order_by("pk")  # ordre croissant → on garde les plus anciens en cas de doublon
    )

    if not cic_transactions:
        return

    # Calculer les nouveaux hashes
    new_hashes = {}  # pk → new_hash
    for tx in cic_transactions:
        rib = tx.account.contract_number
        raw = f"{rib}|{tx.date}|{tx.amount}|{tx.description_raw}"
        new_hashes[tx.pk] = hashlib.sha256(raw.encode()).hexdigest()

    # Détecter les doublons : si deux transactions ont le même nouveau hash,
    # on garde la plus ancienne (pk le plus bas) et on supprime les autres.
    # Cela peut arriver si une transaction a été réimportée à cause du bug row_idx.
    seen_hashes = {}  # new_hash → pk de la transaction gardée
    pks_to_delete = []

    for tx in cic_transactions:
        nh = new_hashes[tx.pk]
        if nh in seen_hashes:
            # Doublon — cette transaction est une réimportation parasite
            pks_to_delete.append(tx.pk)
        else:
            seen_hashes[nh] = tx.pk

    if pks_to_delete:
        deleted_count = Transaction.objects.filter(pk__in=pks_to_delete).delete()[0]
        print(
            f"  [migration] Suppression de {deleted_count} transactions CIC en double"
        )

    # Mettre à jour import_hash pour les transactions conservées
    pks_to_update = [pk for pk in new_hashes if pk not in pks_to_delete]
    updated = 0
    for pk in pks_to_update:
        Transaction.objects.filter(pk=pk).update(import_hash=new_hashes[pk])
        updated += 1

    print(
        f"  [migration] {updated} transactions CIC re-hashées (nouvelle formule sans row_idx)"
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("transactions", "0008_import_log_storage_fields"),
    ]

    operations = [
        migrations.RunPython(rehash_cic_transactions, reverse_code=noop),
    ]
