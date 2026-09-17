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
    """CSV UBS ANCIEN format (colonne « Monnaie »). Contient 3 transactions."""
    return FIXTURES_DIR / "ubs_sample.csv"


@pytest.fixture
def ubs_csv_devise_path() -> Path:
    """
    CSV UBS NOUVEAU format (colonne « Devise ») — mêmes 3 transactions.

    UBS a renommé « Monnaie » en « Devise » dans ses exports. Les deux formats
    doivent être acceptés : les anciens fichiers restent réimportables (le
    dossier d'archives en contient), et les nouveaux doivent passer.
    """
    return FIXTURES_DIR / "ubs_sample_devise.csv"


@pytest.fixture
def ubs_csv_empty_savings_path() -> Path:
    """
    CSV UBS d'un compte d'épargne SANS mouvement (nouveau format).

    Variante réelle : 7 lignes de metadata au lieu de 8 (pas de « Évaluation en »),
    « Solde final:;; » vide, et zéro ligne de transaction. Sert de garde-fou
    contre un crash sur un export parfaitement légitime.
    """
    return FIXTURES_DIR / "ubs_sample_empty_savings.csv"


@pytest.fixture
def tsb_csv_path() -> Path:
    """
    CSV TSB de test — 8 transactions couvrant les pièges du format réel.

    Identifiants FACTICES (sort code 00-00-00, compte 00000000, carte 1234) :
    les libellés TSB réels encastrent le sort code et le numéro du compte
    d'épargne du titulaire, qui n'ont rien à faire dans un fichier committé
    (SR-008, gardé par tests/test_reference_data.py).
    """
    return FIXTURES_DIR / "tsb_sample.csv"
