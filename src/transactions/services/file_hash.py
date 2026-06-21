"""
transactions/services/file_hash.py — hash d'un fichier d'import (déduplication).

compute_file_hash(path) → SHA1 hex. Stocké dans ImportLog.file_hash pour détecter
si le même fichier exact a déjà été importé. Pas un usage crypto — juste une clé
d'égalité. Appelé par les commandes import_* et l'orchestrateur d'import web.
"""

import hashlib
from pathlib import Path


def compute_file_hash(filepath: Path) -> str:
    """
    Compute the SHA1 hash of a file's raw content.

    Used to detect if the exact same file was already imported.
    Stored in ImportLog.file_hash (unique=True in DB).

    Why SHA1?
    - Same choice as import_hash (per-row deduplication in connectors)
    - SHA1 is fast, and we're not using it for security — just equality checks
    - 40-char hex — fits CharField(max_length=64) qui couvre aussi les SHA256 dérivés CIC

    Why read in 64KB chunks?
    - Avoids loading the entire file into memory — safe for large Excel files
    """
    # usedforsecurity=False : on utilise SHA1 pour de l'équality check (déduplication),
    # pas pour la crypto. Sans ce flag, bandit B324 et certains environnements FIPS
    # rejettent SHA1 — alors qu'on n'en fait pas un usage cryptographique.
    sha1 = hashlib.sha1(usedforsecurity=False)  # nosemgrep
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha1.update(chunk)
    return sha1.hexdigest()
