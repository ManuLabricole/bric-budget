"""
transactions/services/ — services du domaine transactions (package, #183).

Un module par service (même esprit que le package racine services/) :
    import_service.py    — ImportService + ImportResult (écrit un batch en DB)
    internal_transfer.py — sync_internal_transfer + INTERNAL_TRANSFER_SLUG
    file_hash.py         — compute_file_hash (déduplication fichier)

Ré-exports pour compat : `from transactions.services import ImportService` continue
de marcher après le découpage du fichier en package.

NB : get_exchange_rate (appel d'API externe transverse) NE vit PAS ici mais dans
le package racine `services/exchange_rates.py` (jumeau de logos.py) — l'importer
depuis là. cf. services/__init__.py pour la convention.
"""

from .file_hash import compute_file_hash
from .import_service import ImportResult, ImportService
from .internal_transfer import INTERNAL_TRANSFER_SLUG, sync_internal_transfer

__all__ = [
    "INTERNAL_TRANSFER_SLUG",
    "ImportResult",
    "ImportService",
    "compute_file_hash",
    "sync_internal_transfer",
]
