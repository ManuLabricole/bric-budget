"""
transactions/services/internal_transfer.py — flags virement interne.

sync_internal_transfer(tx) aligne is_internal_transfer / is_ignored sur la catégorie
"Virements". Appelé aux 3 points de catégorisation : import (import_service), vue
manuelle (budget), batch (apply_rules). INTERNAL_TRANSFER_SLUG = point central du slug.
"""

# Slug de la catégorie "Virements" — point central pour éviter la duplication.
# Si le slug change un jour → changer ici uniquement.
INTERNAL_TRANSFER_SLUG = "virements"


def sync_internal_transfer(tx) -> list[str]:
    """
    Synchronise is_internal_transfer et is_ignored selon la catégorie de la transaction.

    Règle métier :
      - category.slug == "virements" → is_internal_transfer=True, is_ignored=True
      - toute autre catégorie         → is_internal_transfer=False, is_ignored=False

    Pourquoi reset is_ignored à False quand on quitte "Virements" ?
        Si on a catégorisé → virements (flags True) puis on recatégorise → autre,
        c'est délibéré : on veut que la transaction réapparaisse dans les totaux.
        L'utilisateur peut re-ignorer manuellement ensuite.

    Retourne la liste des champs modifiés — utile pour save(update_fields=...) ou
    bulk_update dans apply_rules.

    Appelé depuis :
      - budget_categorize_transaction (vue manuelle)
      - ImportService._build_transaction (import CSV)
      - apply_rules command (batch recatégorisation)
    """
    is_internal = bool(tx.category and tx.category.slug == INTERNAL_TRANSFER_SLUG)
    changed = []
    if tx.is_internal_transfer != is_internal:
        tx.is_internal_transfer = is_internal
        changed.append("is_internal_transfer")
    if tx.is_ignored != is_internal:
        tx.is_ignored = is_internal
        changed.append("is_ignored")
    return changed
