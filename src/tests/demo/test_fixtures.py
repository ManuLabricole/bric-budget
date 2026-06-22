"""
tests/demo/test_fixtures.py — garde-fou SR-008 sur les fixtures committées (#118).

Les fixtures de démo sont VERSIONNÉES (pas gitignorées) → on garantit par test
qu'elles ne contiennent QUE des identifiants synthétiques. Le hook anti-IBAN ne
scanne que les .py ; ici on scanne les CSV committés. (Les RIB CIC vivent dans le
.xlsx binaire, synthétiques par construction — couverts par test_generators.)
"""

import re
from pathlib import Path

from django.conf import settings

from demo import profiles

FIXTURES_DIR = Path(settings.BASE_DIR) / "demo" / "fixtures"

# IBAN synthétiques autorisés (sans espaces) — seuls admis dans les fixtures.
_ALLOWED_IBANS = {
    profiles.DEMO_UBS_CHECKING_IBAN.replace(" ", ""),
    profiles.DEMO_UBS_SAVINGS_IBAN.replace(" ", ""),
}


def test_committed_fixtures_exist():
    expected = {
        "ubs/ubs_checking_demo.csv",
        "ubs/ubs_savings_demo.csv",
        "yuh/yuh_demo.csv",
        "yuh/yuh_savings_demo.csv",
        "cic/cic_demo.xlsx",
    }
    present = {
        str(p.relative_to(FIXTURES_DIR)) for p in FIXTURES_DIR.rglob("*") if p.is_file()
    }
    assert expected <= present, f"fixtures manquantes : {expected - present}"


def test_csv_fixtures_have_only_synthetic_ibans():
    """SR-008 : tout IBAN CH/FR dans les CSV committés est un IBAN synthétique connu."""
    for path in FIXTURES_DIR.rglob("*.csv"):
        content = path.read_text(encoding="utf-8-sig")
        for raw in re.findall(r"(?:CH|FR)\d{2}[\s\d]{8,}", content):
            normalized = re.sub(r"\s", "", raw)
            assert normalized in _ALLOWED_IBANS, (
                f"{path.name}: IBAN non synthétique {raw!r}"
            )
