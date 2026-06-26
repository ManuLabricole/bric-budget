"""
tests/config/test_sentry_scrub.py — scrubbing PII Sentry (#259, SR-008).

Prouve qu'aucun identifiant bancaire ne part vers Sentry, même profondément imbriqué
dans l'événement, et que les données NON sensibles sont préservées.
"""

from config.sentry import SCRUBBED, scrub_sensitive


def _send(event):
    # hint est ignoré par notre before_send ; on passe un dict vide.
    return scrub_sensitive(event, {})


def test_scrubs_sensitive_keys_in_request_and_extra():
    event = {
        "request": {"data": {"iban": "CH9300762011623852957", "label": "Loyer"}},
        "extra": {"account": {"contract_number": "ABC-123", "name": "Livret"}},
    }

    out = _send(event)

    assert out["request"]["data"]["iban"] == SCRUBBED
    assert out["extra"]["account"]["contract_number"] == SCRUBBED
    # Les valeurs non sensibles restent intactes.
    assert out["request"]["data"]["label"] == "Loyer"
    assert out["extra"]["account"]["name"] == "Livret"


def test_scrubs_in_nested_lists():
    event = {"extra": {"accounts": [{"rib": "12345"}, {"iban": "FR76..."}]}}

    out = _send(event)

    assert out["extra"]["accounts"][0]["rib"] == SCRUBBED
    assert out["extra"]["accounts"][1]["iban"] == SCRUBBED


def test_case_insensitive_and_substring_match():
    event = {"extra": {"User_IBAN": "X", "bank_account_number": "Y", "title": "ok"}}

    out = _send(event)

    assert out["extra"]["User_IBAN"] == SCRUBBED  # casse ignorée
    assert out["extra"]["bank_account_number"] == SCRUBBED  # sous-chaîne
    assert out["extra"]["title"] == "ok"


def test_no_request_or_extra_is_safe():
    # Un événement sans request/extra ne doit pas planter.
    assert _send({}) == {}
