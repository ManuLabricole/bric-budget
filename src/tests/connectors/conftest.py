"""
tests/connectors/conftest.py — Fixtures locales aux tests de connecteurs.

La fixture cic_file a été déplacée dans src/tests/conftest.py (niveau parent)
pour être accessible aussi aux tests d'intégration dans src/tests/integration/.

Ce fichier ne contient que les fixtures propres aux connecteurs :
    - yuh_csv_path : chemin vers le CSV Yuh de test
    - ubs_csv_path : chemin vers le CSV UBS de test
"""

from pathlib import Path

import pytest

# Chemin vers les fixtures CSV statiques (CSV sont des fichiers texte, on peut les
# versionner lisiblement — pas besoin de les créer programmatiquement)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def yuh_csv_path() -> Path:
    """Chemin vers le CSV Yuh de test. Contient 4 transactions + 1 REWARD_RECEIVED."""
    return FIXTURES_DIR / "yuh_sample.csv"


@pytest.fixture
def ubs_csv_path() -> Path:
    """Chemin vers le CSV UBS de test. Contient 3 transactions."""
    return FIXTURES_DIR / "ubs_sample.csv"
