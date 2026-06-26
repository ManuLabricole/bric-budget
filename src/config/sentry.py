"""
config/sentry.py — Scrubbing PII pour Sentry (#259).

`scrub_sensitive` est passé en `before_send` à `sentry_sdk.init` (cf. settings.py).
Extrait ici pour être TESTABLE : on prouve qu'aucun identifiant bancaire ne part
vers le cloud Sentry, où qu'il soit dans l'événement (défense en profondeur SR-008).

Défense en COUCHES (l'audit sécu #260 a montré qu'un seul niveau ne suffit pas) :
  1. settings : `send_default_pii=False` (pas de cookies/IP), `include_local_variables
     =False` (⛔ coupe la VRAIE fuite : les variables locales des stack traces — un
     IBAN/montant/ligne CSV dans une frame), `max_request_body_size="never"`.
  2. ce before_send : parcourt TOUT l'événement (request, extra, exception, frames,
     breadcrumbs, message) et masque :
       - par NOM DE CLÉ (iban, rib, contract_number, account_number),
       - par PATTERN DE VALEUR (un IBAN sous une clé neutre comme `value`/`arg0`).
"""

from __future__ import annotations

import re

from sentry_sdk.types import Event, Hint

# Une clé qui CONTIENT l'un de ces fragments (insensible à la casse) est masquée.
SENSITIVE_KEY_HINTS = ("iban", "rib", "contract_number", "account_number")
SCRUBBED = "[scrubbed]"

# IBAN : 2 lettres pays + 2 chiffres clé + 10–30 alphanum (CH=21, FR=27…).
# Masqué PARTOUT (message d'exception, vars de frame, breadcrumb), même sous une
# clé neutre — le matching par nom de clé seul ne voit pas ces cas.
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")


def _scrub_str(value: str) -> str:
    return _IBAN_RE.sub(SCRUBBED, value)


def _walk(obj: object) -> object:
    """Masque en place ; renvoie la version masquée pour les chaînes (immuables)."""
    if isinstance(obj, dict):
        for key in list(obj):
            if isinstance(key, str) and any(
                hint in key.lower() for hint in SENSITIVE_KEY_HINTS
            ):
                obj[key] = SCRUBBED  # clé sensible → valeur entière masquée
            else:
                obj[key] = _walk(obj[key])
        return obj
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            obj[i] = _walk(item)
        return obj
    if isinstance(obj, str):
        return _scrub_str(obj)  # IBAN sous clé neutre / message / breadcrumb
    return obj


def scrub_sensitive(event: Event, hint: Hint) -> Event:
    """`before_send` Sentry : masque les identifiants bancaires dans TOUT l'event."""
    _walk(event)
    return event
