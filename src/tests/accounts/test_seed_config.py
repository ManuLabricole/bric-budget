"""
tests/accounts/test_seed_config.py — validation du fichier de seed des comptes.

Tests PURS PYTHON — aucun accès à la base (le loader ne touche pas l'ORM).

Ce qui est gardé ici : le fichier de seed porte des IBAN réels et pilote la
création de comptes. Une entrée mal formée doit échouer AVEC UN MESSAGE UTILE,
jamais produire un compte silencieusement incomplet — un compte sans identité
d'import ne se découvre qu'au moment où un relevé refuse de s'y rattacher.
"""

import json
from decimal import Decimal

import pytest

from accounts.seed_config import SeedConfigError, load_seed_config


def write(tmp_path, payload):
    """Écrit un fichier de seed et renvoie son chemin."""
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_account(**overrides):
    base = {
        "institution": "ubs",
        "name": "UBS Courant",
        "type": "checking",
        "currency": "CHF",
        "iban": "CH0000000000000000000",
    }
    return {**base, **overrides}


def valid_payload(*accounts):
    return {
        "user_email": "toi@example.com",
        "accounts": list(accounts) or [valid_account()],
    }


# =============================================================================
# Cas nominal
# =============================================================================


def test_loads_a_valid_file(tmp_path):
    config = load_seed_config(write(tmp_path, valid_payload()))
    assert config.user_email == "toi@example.com"
    assert len(config.accounts) == 1
    assert config.accounts[0].name == "UBS Courant"


def test_iban_spaces_are_stripped(tmp_path):
    """
    Les banques écrivent l'IBAN par groupes de 4 ; les connecteurs le normalisent
    sans espaces avant de matcher. Sans cette normalisation, un IBAN copié depuis
    l'e-banking ne correspondrait JAMAIS au compte, sans message d'erreur.
    """
    payload = valid_payload(valid_account(iban="CH94 0024 3243 6933 8240 P"))
    assert load_seed_config(write(tmp_path, payload)).accounts[0].iban == (
        "CH940024324369338240P"
    )


def test_empty_iban_becomes_none_not_empty_string(tmp_path):
    """
    Account.iban est unique ET nullable : deux comptes à "" violeraient la
    contrainte, deux NULL cohabitent. La distinction est donc structurante.
    """
    payload = valid_payload(valid_account(iban="", contract_number="ABC123"))
    assert load_seed_config(write(tmp_path, payload)).accounts[0].iban is None


def test_interest_rate_is_decimal_not_float(tmp_path):
    """
    SR-002 : Decimal(str(x)), jamais Decimal(float).

    On vérifie la valeur exacte, pas seulement le type : Decimal(3.0) vaut
    3.0000000000000004…, ce qu'un `isinstance(..., Decimal)` laisserait passer.
    """
    payload = valid_payload(
        valid_account(
            type="savings", interest_rate="3.00", iban=None, contract_number="X1"
        )
    )
    rate = load_seed_config(write(tmp_path, payload)).accounts[0].interest_rate
    assert rate == Decimal("3.00")
    assert str(rate) == "3.00"


def test_underscore_keys_are_ignored(tmp_path):
    """Les clés « _note » servent de commentaires dans le fichier réel."""
    payload = valid_payload(valid_account(_note="un commentaire libre"))
    assert load_seed_config(write(tmp_path, payload)).accounts[0].name == "UBS Courant"


# =============================================================================
# has_identity — un compte sans identité ne peut recevoir aucun import
# =============================================================================


def test_account_without_any_identity_has_no_identity(tmp_path):
    payload = valid_payload(valid_account(iban="", contract_number=""))
    assert load_seed_config(write(tmp_path, payload)).accounts[0].has_identity is False


def test_account_with_only_contract_number_has_identity(tmp_path):
    """CIC/TSB s'identifient par n° de contrat, pas par IBAN."""
    payload = valid_payload(valid_account(iban="", contract_number="100961802700064"))
    assert load_seed_config(write(tmp_path, payload)).accounts[0].has_identity is True


# =============================================================================
# Rejets — chaque message doit désigner le coupable
# =============================================================================


def test_unknown_key_is_rejected(tmp_path):
    """
    Une faute de frappe (« ibna ») ignorée en silence créerait un compte sans
    identité, découvert des semaines plus tard devant un import qui échoue.
    """
    payload = valid_payload(valid_account(ibna="CH00"))
    with pytest.raises(SeedConfigError, match="ibna"):
        load_seed_config(write(tmp_path, payload))


def test_unsupported_type_is_rejected(tmp_path):
    payload = valid_payload(valid_account(type="pension_3a"))
    with pytest.raises(SeedConfigError, match="pension_3a"):
        load_seed_config(write(tmp_path, payload))


def test_unknown_currency_is_rejected(tmp_path):
    payload = valid_payload(valid_account(currency="XXX"))
    with pytest.raises(SeedConfigError, match="XXX"):
        load_seed_config(write(tmp_path, payload))


def test_missing_name_is_rejected(tmp_path):
    account = valid_account()
    del account["name"]
    with pytest.raises(SeedConfigError, match="name"):
        load_seed_config(write(tmp_path, valid_payload(account)))


def test_non_boolean_is_active_is_rejected(tmp_path):
    """« "false" » (chaîne) est truthy en Python — l'accepter inverserait l'intention."""
    payload = valid_payload(valid_account(is_active="false"))
    with pytest.raises(SeedConfigError, match="is_active"):
        load_seed_config(write(tmp_path, payload))


def test_non_numeric_interest_rate_is_rejected(tmp_path):
    payload = valid_payload(valid_account(type="savings", interest_rate="beaucoup"))
    with pytest.raises(SeedConfigError, match="interest_rate"):
        load_seed_config(write(tmp_path, payload))


def test_duplicate_iban_in_file_is_rejected(tmp_path):
    """
    Deux comptes au même IBAN lèveraient une IntegrityError EN COURS d'écriture
    (Account.iban est unique). On préfère le dire avant, en nommant les deux.
    """
    payload = valid_payload(
        valid_account(name="Compte A"),
        valid_account(name="Compte B"),
    )
    with pytest.raises(SeedConfigError, match="Compte A.*Compte B"):
        load_seed_config(write(tmp_path, payload))


def test_duplicate_contract_number_same_institution_is_rejected(tmp_path):
    """
    contract_number n'est PAS unique en base : le doublon passerait, et la
    résolution à l'import choisirait arbitrairement l'un des deux comptes.
    """
    payload = valid_payload(
        valid_account(name="CIC A", institution="cic", iban="", contract_number="1234"),
        valid_account(name="CIC B", institution="cic", iban="", contract_number="1234"),
    )
    with pytest.raises(SeedConfigError, match="CIC A.*CIC B"):
        load_seed_config(write(tmp_path, payload))


def test_same_contract_number_in_two_institutions_is_allowed(tmp_path):
    """Deux banques peuvent numéroter leurs contrats à l'identique — pas un conflit."""
    payload = valid_payload(
        valid_account(name="CIC", institution="cic", iban="", contract_number="1234"),
        valid_account(name="TSB", institution="tsb", iban="", contract_number="1234"),
    )
    assert len(load_seed_config(write(tmp_path, payload)).accounts) == 2


def test_missing_file_explains_how_to_create_it(tmp_path):
    with pytest.raises(SeedConfigError, match="accounts.example.json"):
        load_seed_config(tmp_path / "absent.json")


def test_malformed_json_reports_the_line(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text('{"user_email": "x",,}', encoding="utf-8")
    with pytest.raises(SeedConfigError, match="ligne"):
        load_seed_config(path)


def test_empty_accounts_list_is_rejected(tmp_path):
    payload = {"user_email": "toi@example.com", "accounts": []}
    with pytest.raises(SeedConfigError, match="accounts"):
        load_seed_config(write(tmp_path, payload))


def test_unknown_top_level_key_is_rejected(tmp_path):
    payload = {**valid_payload(), "acounts": []}
    with pytest.raises(SeedConfigError, match="acounts"):
        load_seed_config(write(tmp_path, payload))
