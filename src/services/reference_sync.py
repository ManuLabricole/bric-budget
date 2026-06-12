"""
services/reference_sync.py — synchronisation idempotente d'un enregistrement.

Les seeds de référentiel (seed_banks, seed_categories, futurs catalogues) veulent
un feedback HONNÊTE : créé / modifié / inchangé — pas « mis à jour » systématique.

Pourquoi pas update_or_create() ?
    Il émet un UPDATE SQL même quand AUCUN champ ne change → son compteur
    `created=False` dit seulement « existait déjà », jamais « a réellement changé ».
    sync_record() compare les champs AVANT d'écrire : il ne touche la DB que sur
    un vrai diff (préserve aussi les `auto_now`) et dit exactement ce qui s'est passé.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

M = TypeVar("M", bound=models.Model)


class SyncResult(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def sync_record(
    model: type[M],
    *,
    lookup: dict[str, Any],
    defaults: dict[str, Any],
) -> tuple[M, SyncResult]:
    """
    Crée/met à jour l'instance de `model` identifiée par `lookup`, en n'écrivant
    QUE si un champ de `defaults` diffère réellement.

    Retourne (instance, résultat) où résultat ∈ {CREATED, UPDATED, UNCHANGED}.
    """
    # _default_manager (et ObjectDoesNotExist) plutôt que model.objects /
    # model.DoesNotExist : django-stubs ne résout pas ces attributs sur un
    # type générique `type[M]`, _default_manager si.
    manager = model._default_manager
    try:
        obj = manager.get(**lookup)
    except ObjectDoesNotExist:
        obj = manager.create(**lookup, **defaults)
        return obj, SyncResult.CREATED

    changed_fields = []
    for field, value in defaults.items():
        if isinstance(value, models.Model):
            # FK : comparer par pk sans charger la relation (évite une requête).
            if getattr(obj, f"{field}_id") != value.pk:
                changed_fields.append(field)
        elif getattr(obj, field) != value:
            changed_fields.append(field)

    if not changed_fields:
        return obj, SyncResult.UNCHANGED

    for field in changed_fields:
        setattr(obj, field, defaults[field])
    obj.save(update_fields=changed_fields)
    return obj, SyncResult.UPDATED
