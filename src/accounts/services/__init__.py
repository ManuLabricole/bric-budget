"""
accounts/services/ — services métier de l'app accounts (package depuis #292).

Re-export plat : `from accounts.services import create_account` continue de
marcher. Un module par opération (create / update), builders partagés.
"""

from .create import create_account
from .update import archive_account, update_account

__all__ = [
    "archive_account",
    "create_account",
    "update_account",
]
