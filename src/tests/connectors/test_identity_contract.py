"""
tests/connectors/test_identity_contract.py — contrat d'identité des connecteurs (#274).

resolve_accounts() est devenu data-driven : il ne connaît plus les banques (plus de
isinstance), il interroge connector.list_account_identities() + INSTITUTION_SLUG +
IDENTITY_FIELD. Ce contrat est la fondation de la scalabilité (ajouter une banque =
écrire son connecteur). On le teste directement, par connecteur :

    Yuh  → IDENTITY_FIELD=None  → [] (aucune identité dans le fichier → picker)
    UBS  → IDENTITY_FIELD=iban  → 1 identité (IBAN normalisé)
    CIC  → IDENTITY_FIELD=contract_number → N identités (1 par feuille)
"""

import pytest

from connectors.cic.parser import CICConnector
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector


def test_yuh_declares_no_identity_field():
    """Yuh n'expose aucun identifiant → IDENTITY_FIELD None → résolution par picker."""
    assert YuhConnector.INSTITUTION_SLUG == "yuh"
    assert YuhConnector.IDENTITY_FIELD is None


def test_yuh_returns_no_identities(yuh_csv_path):
    """Fichier Yuh → liste vide : rien à matcher, l'utilisateur choisira le compte."""
    assert YuhConnector().list_account_identities(yuh_csv_path) == []


def test_ubs_declares_iban_identity_field():
    """UBS résout sur Account.iban."""
    assert UBSConnector.INSTITUTION_SLUG == "ubs"
    assert UBSConnector.IDENTITY_FIELD == "iban"


def test_ubs_returns_single_normalized_identity(ubs_csv_path):
    """UBS → 1 identité = IBAN ligne 2 normalisé (sans espaces), pas de feuille."""
    identities = UBSConnector().list_account_identities(ubs_csv_path)

    assert len(identities) == 1
    assert identities[0].identifier == "CH0000000000000000000"
    assert identities[0].sheet_name is None


def test_ubs_raises_when_identifier_missing(ubs_csv_path):
    """IDENTITY_FIELD défini mais identifiant introuvable = fichier corrompu → ValueError."""
    connector = UBSConnector()
    with pytest.raises(ValueError, match="corrompu"):
        # extract_account_identifier patché à None via une sous-classe minimale
        connector.extract_account_identifier = lambda _p: None  # type: ignore[method-assign]
        connector.list_account_identities(ubs_csv_path)


def test_cic_declares_contract_number_identity_field():
    """CIC résout sur Account.contract_number (RIB)."""
    assert CICConnector.INSTITUTION_SLUG == "cic"
    assert CICConnector.IDENTITY_FIELD == "contract_number"


def test_cic_returns_one_identity_per_sheet(cic_file):
    """CIC multi-feuilles → 1 identité (RIB normalisé + nom de feuille) par compte."""
    identities = CICConnector().list_account_identities(cic_file)

    ribs = {i.identifier for i in identities}
    assert ribs == {"100961802700064764601", "100961802700087654321"}
    # chaque identité porte son nom de feuille (cible le bon onglet au parse)
    assert all(i.sheet_name for i in identities)
