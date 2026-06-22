"""
tests/demo/test_generators.py — round-trip des générateurs de démo (#118).

On prouve que les fichiers générés sont lus SANS erreur par les VRAIS connecteurs
(détection + parsing + identifiant) — c'est la garantie que le seed passera bien
par le pipeline réel. Aucun accès DB (parsing pur).
"""

import re
from datetime import date
from random import Random

from connectors.cic.parser import CICConnector
from connectors.resolver import detect_connector
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector
from demo import generators, profiles

ANCHOR = date(2026, 6, 1)


def test_ubs_checking_detected_and_parsed(tmp_path):
    path = generators.write_bank_file(
        "ubs_checking", tmp_path, months=12, anchor=ANCHOR
    )
    assert isinstance(detect_connector(path), UBSConnector)

    txs = UBSConnector().parse(path)
    assert len(txs) > 80  # ~8 flux récurrents × 12 mois

    # IBAN synthétique correctement extrait (sans espaces) → résolvable par le seeder.
    ident = UBSConnector().extract_account_identifier(path)
    assert ident == profiles.DEMO_UBS_CHECKING_IBAN.replace(" ", "")

    # Salaire = 1 crédit positif par mois.
    salaries = [t for t in txs if "SALAIRE" in t["description_raw"].upper()]
    assert len(salaries) == 12
    assert all(t["amount"] > 0 for t in salaries)

    # Loyer = débit négatif.
    rents = [t for t in txs if "LOYER" in t["description_raw"].upper()]
    assert rents and all(t["amount"] < 0 for t in rents)


def test_ubs_savings_parses_and_has_distinct_iban(tmp_path):
    path = generators.write_bank_file("ubs_savings", tmp_path, months=6, anchor=ANCHOR)
    txs = UBSConnector().parse(path)
    assert len(txs) >= 5  # ~1 flux × 6 mois
    ident = UBSConnector().extract_account_identifier(path)
    assert ident == profiles.DEMO_UBS_SAVINGS_IBAN.replace(" ", "")
    assert ident != profiles.DEMO_UBS_CHECKING_IBAN.replace(" ", "")


def test_ubs_files_have_disjoint_import_hashes(tmp_path):
    """No de transaction unique par compte → import_hash UBS disjoints. Sinon les
    transactions de l'épargne seraient dédupliquées contre le compte courant
    (import_hash global) → 0 transaction importée (régression réelle attrapée en live)."""
    chk = generators.write_bank_file("ubs_checking", tmp_path, months=6, anchor=ANCHOR)
    sav = generators.write_bank_file("ubs_savings", tmp_path, months=6, anchor=ANCHOR)
    chk_hashes = {t["import_hash"] for t in UBSConnector().parse(chk)}
    sav_hashes = {t["import_hash"] for t in UBSConnector().parse(sav)}
    assert chk_hashes and sav_hashes
    assert chk_hashes.isdisjoint(sav_hashes)


def test_yuh_detected_and_parsed(tmp_path):
    path = generators.write_bank_file("yuh", tmp_path, months=12, anchor=ANCHOR)
    assert isinstance(detect_connector(path), YuhConnector)

    txs = YuhConnector().parse(path)
    assert len(txs) > 50
    # Profil carte : que des débits, tous avec le last-four synthétique.
    assert all(t["amount"] < 0 for t in txs)
    assert all(t["card_last_four"] == profiles.DEMO_YUH_CARD_LAST_FOUR for t in txs)


def test_cic_detected_sheets_and_parsed(tmp_path):
    """Round-trip CIC : le .xlsx généré est détecté, ses 2 feuilles découvertes
    (RIB normalisés + type + solde), et parsé sans erreur via le VRAI connecteur."""
    path = generators.write_bank_file("cic", tmp_path, months=12, anchor=ANCHOR)

    # Détection : .xlsx + feuille "Vos comptes" → CICConnector.
    assert isinstance(detect_connector(path), CICConnector)

    # Découverte des feuilles : 2 comptes, RIB normalisés (sans espaces), type, solde.
    sheets = CICConnector().get_account_sheets(path)
    assert len(sheets) == 2
    ribs = {s["rib"] for s in sheets}
    # RIB normalisés = source "00000 00000 00000000001/2" sans espaces (21 chiffres).
    assert ribs == {"000000000000000000001", "000000000000000000002"}
    assert all(" " not in rib for rib in ribs)  # bien normalisés
    assert {s["account_type_hint"] for s in sheets} == {"checking", "savings"}
    assert all(s["balance"] is not None for s in sheets)

    # Parsing : transactions en EUR, débits négatifs / crédits positifs.
    txs = CICConnector().parse(path)
    assert len(txs) > 0
    assert all(t["currency"] == "EUR" for t in txs)
    debits = [t for t in txs if t["amount"] < 0]
    credits = [t for t in txs if t["amount"] > 0]
    assert debits and credits


def test_cic_files_have_disjoint_import_hashes(tmp_path):
    """Le RIB entre dans l'import_hash CIC → les 2 feuilles (RIB distincts) ont des
    hashes disjoints. Sinon les transactions du livret seraient dédupliquées contre
    le compte courant (import_hash global) comme pour UBS."""
    path = generators.write_bank_file("cic", tmp_path, months=12, anchor=ANCHOR)
    sheets = CICConnector().get_account_sheets(path)
    by_name = {s["sheet_name"]: s for s in sheets}
    chk = {t["import_hash"] for t in CICConnector().parse_sheet(path, "Cpt courant")}
    sav = {t["import_hash"] for t in CICConnector().parse_sheet(path, "Cpt livret")}
    # Les deux feuilles attendues existent bien.
    assert "Cpt courant" in by_name and "Cpt livret" in by_name
    assert chk and sav
    assert chk.isdisjoint(sav)


def test_generation_is_deterministic():
    a = generators.generate_yuh_csv(
        profiles.YUH_CARD_FLOWS,
        card_last_four="1150",
        months=6,
        anchor=ANCHOR,
        rng=Random(1),
    )
    b = generators.generate_yuh_csv(
        profiles.YUH_CARD_FLOWS,
        card_last_four="1150",
        months=6,
        anchor=ANCHOR,
        rng=Random(1),
    )
    assert a == b


def test_only_synthetic_ibans(tmp_path):
    """SR-008 : aucun IBAN avec des chiffres non nuls (= que des IBAN tout-zéro)."""
    path = generators.write_bank_file("ubs_checking", tmp_path, months=3, anchor=ANCHOR)
    content = path.read_text(encoding="utf-8-sig")
    for iban in re.findall(r"CH\d{2}[\s\d]{8,}", content):
        digits = re.sub(r"\D", "", iban)
        assert set(digits) <= {"0"}, f"IBAN non synthétique détecté : {iban}"
