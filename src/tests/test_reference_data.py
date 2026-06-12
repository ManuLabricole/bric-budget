"""
tests/test_reference_data.py — garde SR-008 sur TOUS les référentiels committés.

Les référentiels vivent dans les apps (<app>/reference/*.json,
accounts/institutions_config.py) : surface éclatée par design (Two Scoops),
donc l'audit « aucune donnée perso/bancaire » est automatisé ici — chaque CI
re-vérifie ce qu'un œil humain n'a validé qu'une fois.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

SRC = Path(settings.BASE_DIR)

# IBAN : 2 lettres + 2 chiffres + 10+ alphanum. Numéros longs : 11+ chiffres
# consécutifs (un n° de contrat réel ; les plafonds type 7056 passent).
_SENSITIVE_PATTERNS = [
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,}\b"),
    re.compile(r"\b\d{11,}\b"),
]


def _reference_files() -> list[Path]:
    files = sorted(SRC.glob("*/reference/*.json"))
    files.append(SRC / "accounts" / "institutions_config.py")
    return files


def test_reference_files_exist():
    """Le scan doit scanner quelque chose — un glob vide serait un faux vert."""
    files = _reference_files()
    assert any(f.name == "categories.json" for f in files)
    assert all(f.exists() for f in files)


@pytest.mark.parametrize("path", _reference_files(), ids=lambda p: p.name)
def test_reference_file_has_no_sensitive_data(path: Path):
    content = path.read_text(encoding="utf-8")
    for pattern in _SENSITIVE_PATTERNS:
        hits = pattern.findall(content)
        assert not hits, f"Motif sensible (SR-008) dans {path.name} : {hits[:3]}"
