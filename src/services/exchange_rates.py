"""
services/exchange_rates.py — micro-service : taux de change via DB ou frankfurter.app.

Contrat :
    get_exchange_rate(date, from_currency, to_currency="CHF") → Decimal | None
        DB d'abord (cache ExchangeRate), API ensuite, None si échec réseau —
        ne lève JAMAIS (un import ne doit pas planter pour un taux indisponible).

Appelants : transactions.services.import_service (conversion amount_chf à l'import),
+ tout futur besoin de conversion de devise.

Même esprit que logos.py : appel d'API externe transverse, isolé hors des apps,
testé sans toucher le réseau (les tests mockent l'appel). cf. services/__init__.py.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date as date_type
from decimal import Decimal

from accounts.models import ExchangeRate

logger = logging.getLogger(__name__)


def get_exchange_rate(
    date: date_type, from_currency: str, to_currency: str = "CHF"
) -> Decimal | None:
    """
    Retourne le taux de change from_currency → to_currency pour une date donnée.

    Stratégie : DB d'abord, API ensuite.
        1. Si le taux existe déjà dans ExchangeRate → le retourner directement.
           (Évite un appel réseau à chaque transaction — un import CIC de 200 lignes
           ne fera que quelques appels API, les dates se répétant souvent.)
        2. Si absent → appeler frankfurter.app (API publique, gratuite, pas de clé).
        3. Stocker le résultat dans ExchangeRate pour les appels futurs.
        4. En cas d'erreur réseau ou API → retourner None sans crasher l'import.

    Pourquoi NOT get_or_create ?
        get_or_create passerait le rate=None à la création, puis on devrait le mettre
        à jour. Deux requêtes au lieu d'une. Plus simple : get() → None → appel API
        → create().

    API frankfurter.app — exemple :
        GET https://api.frankfurter.app/2026-03-17?from=EUR&to=CHF
        → {"amount":1.0,"base":"EUR","date":"2026-03-17","rates":{"CHF":0.9321}}

    ⚠️  NOUVEAU CONNECTEUR (devise non-CHF) :
        Si tu ajoutes un compte GBP, CAD, USD... → cette fonction le gère automatiquement.
        frankfurter.app supporte toutes les devises majeures.
        Vérifier que la devise est supportée : https://api.frankfurter.app/currencies
    """
    if from_currency == to_currency:
        return Decimal("1")

    # ── 1. DB d'abord ────────────────────────────────────────────────────────
    # Cache miss = flux normal (pas une erreur avalée) → silence justifié.
    try:  # nosemgrep: silent-except-pass
        existing = ExchangeRate.objects.get(
            date=date, from_currency=from_currency, to_currency=to_currency
        )
        return existing.rate
    except ExchangeRate.DoesNotExist:
        pass  # pas encore en cache → appel API ci-dessous

    # ── 2. Appel API frankfurter.app ─────────────────────────────────────────
    date_str = date.isoformat()  # "2026-03-17"
    url = (
        f"https://api.frankfurter.app/{date_str}?from={from_currency}&to={to_currency}"
    )

    try:
        # frankfurter.app bloque les requêtes sans User-Agent (répond 403).
        # On ajoute un header minimal pour identifier notre client.
        req = urllib.request.Request(url, headers={"User-Agent": "BricBudget/1.0"})
        # nosec B310 : URL construite côté serveur avec scheme `https` hardcodé,
        # pas d'input user → pas de risque d'exfiltration via file:// ou autre scheme.
        with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310
            data = json.loads(response.read().decode())
            rate = Decimal(str(data["rates"][to_currency]))
    except (urllib.error.URLError, KeyError, ValueError) as e:
        # Erreur réseau ou format inattendu → on ne plante pas l'import.
        # La transaction sera créée avec amount_chf=None — mieux que de tout perdre.
        logger.warning(
            "exchange_rate: could not fetch %s→%s for %s: %s",
            from_currency,
            to_currency,
            date_str,
            e,
        )
        return None

    # ── 3. Stocker en DB pour les prochains imports ───────────────────────────
    # get_or_create évite une IntegrityError si deux imports simultanés appellent
    # cette fonction pour la même date/devise en même temps (race condition).
    ExchangeRate.objects.get_or_create(
        date=date,
        from_currency=from_currency,
        to_currency=to_currency,
        defaults={"rate": rate},
    )

    return rate
