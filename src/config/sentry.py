"""
config/sentry.py — Scrubbing PII pour Sentry (#259).

`scrub_sensitive` est passé en `before_send` à `sentry_sdk.init` (cf. settings.py).
Extrait ici pour être TESTABLE (test/test_sentry_scrub.py) : on prouve que les
identifiants bancaires ne partent jamais vers le cloud Sentry, même si une stack
trace les capture (défense en profondeur SR-008).

`send_default_pii=False` côté init coupe déjà cookies / IP / corps de requête ;
ce scrub retire EN PLUS toute valeur dont la CLÉ évoque un identifiant bancaire,
où qu'elle soit dans `request`/`extra` (récursif).
"""

from __future__ import annotations

from sentry_sdk.types import Event, Hint

# Une clé qui CONTIENT l'un de ces fragments (insensible à la casse) est masquée.
SENSITIVE_KEY_HINTS = ("iban", "rib", "contract_number", "account_number")
SCRUBBED = "[scrubbed]"


def _walk(obj: object) -> None:
    """Masque en place les valeurs sous une clé sensible (dicts/listes imbriqués)."""
    if isinstance(obj, dict):
        for key in list(obj):
            if isinstance(key, str) and any(
                hint in key.lower() for hint in SENSITIVE_KEY_HINTS
            ):
                obj[key] = SCRUBBED
            else:
                _walk(obj[key])
    elif isinstance(obj, list):
        for item in obj:
            _walk(item)


def scrub_sensitive(event: Event, hint: Hint) -> Event:
    """`before_send` Sentry : masque les identifiants bancaires avant envoi."""
    _walk(event.get("request", {}))
    _walk(event.get("extra", {}))
    return event
