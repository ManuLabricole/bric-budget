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


# --- Vecteurs trouvés par l'audit sécu #260 (au-delà de request/extra) ---------


def test_scrubs_iban_in_stacktrace_frame_locals():
    """Le vrai vecteur : un IBAN dans les variables locales d'une frame (clé neutre)."""
    event = {
        "exception": {
            "values": [
                {
                    "value": "boom",
                    "stacktrace": {
                        "frames": [{"vars": {"account": "CH9300762011623852957"}}]
                    },
                }
            ]
        }
    }

    out = _send(event)

    frame = out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame["vars"]["account"] == SCRUBBED  # IBAN masqué malgré la clé neutre


def test_scrubs_iban_in_exception_message():
    """Un IBAN injecté dans le message d'exception (clé neutre `value`)."""
    event = {
        "exception": {"values": [{"value": "IBAN FR7630006000011234567890189 KO"}]}
    }

    out = _send(event)

    assert "FR7630006000011234567890189" not in out["exception"]["values"][0]["value"]
    assert SCRUBBED in out["exception"]["values"][0]["value"]


def test_scrubs_iban_in_breadcrumbs():
    event = {"breadcrumbs": {"values": [{"message": "SELECT … CH9300762011623852957"}]}}

    out = _send(event)

    assert "CH9300762011623852957" not in out["breadcrumbs"]["values"][0]["message"]


def test_iban_under_neutral_key_is_scrubbed_by_value_pattern():
    event = {"extra": {"arg0": "CH9300762011623852957", "count": "42"}}

    out = _send(event)

    assert out["extra"]["arg0"] == SCRUBBED  # masqué par PATTERN, pas par clé
    assert out["extra"]["count"] == "42"  # nombre court non touché
