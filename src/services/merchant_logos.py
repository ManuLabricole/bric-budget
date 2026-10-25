"""
services/merchant_logos.py — display_name → logo (seed connu + ajout manuel).

Deux couches, key-spaces disjoints (pas de collision possible) :
  - SEED (Brandfetch Logo API, LIVE) : mot-clé régulier → marque connue,
    résolu par _match_seed() contre transactions/reference/merchant_seed.json.
    L'URL renvoyée pointe DIRECTEMENT sur cdn.brandfetch.io — le serveur ne
    télécharge ni ne cache JAMAIS ce logo, condition explicite du tier gratuit
    Brandfetch (« you must hotlink the logos we serve rather than caching
    them » ; un fetch côté serveur est détecté comme "automated_traffic" et
    bloqué — vérifié empiriquement). Le navigateur du user charge l'image lui-
    même, comme n'importe quelle image externe classique.
  - MANUEL (runtime, MEDIA) : l'utilisateur colle une URL pour UN display_name
    précis (bouton badge sur une transaction) → stocké sous
    icons/merchants/<slugify(display_name)>.<ext> dans le storage MEDIA par
    défaut (bucket S3 en prod), via services.logos.fetch_from_url — même
    primitif que la réparation de logo institution (#128). CE tier-là reste
    téléchargé/caché côté serveur (l'utilisateur peut coller N'IMPORTE quelle
    URL, pas seulement Brandfetch) — gagne TOUJOURS sur le seed (action
    utilisateur explicite).

Limite assumée (#124 — pas de modèle Merchant dans ce lot) : la clé manuelle est
le display_name EXACT, pas un alias flou. Deux variantes textuelles du même
marchand réel exigent 2 ajouts manuels distincts — acceptable en v1 (YAGNI),
résolu proprement plus tard par un vrai modèle Merchant/MerchantAlias si le
besoin se confirme.

Appelant à fort volume (liste de transactions) : get_merchant_logo_map(names)
résout tout en 1 scan disque (manuel, mis en cache) + 1 passage regex par nom
distinct (seed, pur Python — construire une URL Brandfetch ne fait AUCUN I/O)
— jamais de N+1 (même principe que get_institution_icon_map).

NOTE fuzzy : le prototype (management command) a mesuré rapidfuzz en tier de
secours et trouvé un faux positif net ("PARKING" → APCOA Parking, score 100 en
token_set_ratio dès qu'un mot générique est un sous-ensemble de tokens de
l'autre côté). Le fuzzy reste un outil d'EXPLORATION CLI — jamais branché ici,
en résolution live.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from services import logos

logger = logging.getLogger(__name__)

SEED_PATH = (
    Path(__file__).resolve().parent.parent
    / "transactions"
    / "reference"
    / "merchant_seed.json"
)
MERCHANT_LOGO_PREFIX = "icons/merchants"
_MANUAL_CACHE_TTL_SECONDS = 600
_SLUG_MAX_LENGTH = 80

# ── Brandfetch Logo API (seed tier) ──────────────────────────────────────────
# Format d'URL vérifié empiriquement (curl + Referer + UA navigateur — un curl
# nu SANS ces en-têtes est détecté "automated_traffic" et redirigé vers leur
# doc, ce qui a piégé un premier essai) : /domain/<d>/theme/light/w/<n>/h/<n>/
# fallback/404/icon.png?c=<client_id> — tous les modificateurs (theme, taille,
# fallback) sont des SEGMENTS DE CHEMIN, pas des query params (seul `c` en est
# un). fallback/404 (segment, pas ?fallback=404 qui est silencieusement
# ignoré) : sans lui, un domaine inconnu de Brandfetch renvoie leur lettermark
# générique ("B" stylisé) au lieu d'un vrai 404 — trompeur, on préfère notre
# propre bouton "+" à leur placeholder de marque. theme=light : variante
# pensée pour un fond clair (notre badge est TOUJOURS sur bg-white).
BRANDFETCH_CDN_BASE = "https://cdn.brandfetch.io"
_BRANDFETCH_LOGO_SIZE = 48  # 2x la taille CSS du badge (18px) — écrans retina


@dataclass(frozen=True)
class MerchantSeed:
    key: str
    name: str
    domain: str
    pattern: re.Pattern[str]


@functools.lru_cache(maxsize=1)
def load_seed(path: Path = SEED_PATH) -> list[MerchantSeed]:
    """Charge le seed JSON (ordre préservé = ordre de priorité de matching)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds = []
    for entry in data["merchants"]:
        # Frontière de mot à GAUCHE seulement — pas à droite : les banques tronquent
        # ("GOOGLE YOUTUBEPR" = YouTube Premium coupé) et un \b final raterait tout
        # mot-clé suivi directement d'une troncature. \b à gauche seul suffit à éviter
        # les faux positifs par IMBRICATION (ex. "APPLE" dans "SNAPPLE").
        # Deux familles de mots-clés, et le choix se fait dans le SEED, pas par une
        # heuristique de longueur — mesuré sur les données réelles, une règle « tout
        # mot-clé court prend une frontière à droite » perdait plus qu'elle ne gagnait :
        # elle cassait ESSOF108 (16 tx), AMZNMKTPLACE, AGIP9351, ENI9570 — des marchands
        # authentiques que la banque a tronqués — pour ne corriger que « VOI ».
        #
        #   keywords        → frontière GAUCHE seule. Tolère la troncature bancaire
        #                     ("GOOGLE YOUTUBEPR", "ESSOF108").
        #   strict_keywords → frontière des DEUX côtés. Pour un mot-clé qui est aussi
        #                     le début d'un mot courant : « VOI » matchait PRET VOITURE,
        #                     EPARGNE PRECAUTION VOITURE et LAUSANNE SOUS-VOIES.
        loose = entry.get("keywords", [])
        strict = entry.get("strict_keywords", [])
        branches = []
        if loose:
            branches.append(rf"\b(?:{'|'.join(re.escape(k) for k in loose)})")
        if strict:
            branches.append(rf"\b(?:{'|'.join(re.escape(k) for k in strict)})\b")
        pattern = re.compile("|".join(branches))
        seeds.append(
            MerchantSeed(
                key=entry["key"],
                name=entry["name"],
                domain=entry["domain"],
                pattern=pattern,
            )
        )
    return seeds


def normalize(display_name: str) -> str:
    return display_name.upper().strip()


def _match_seed(display_name: str) -> MerchantSeed | None:
    """Premier seed dont un mot-clé apparaît (frontières de mots) — ordre = priorité."""
    normalized = normalize(display_name)
    for seed in load_seed():
        if seed.pattern.search(normalized):
            return seed
    return None


def resolve_seed_key(display_name: str) -> str | None:
    seed = _match_seed(display_name)
    return seed.key if seed else None


def slug_for(display_name: str) -> str:
    """
    Clé de stockage du logo manuel. Peut être VIDE : slugify("日本") == "", comme tout
    libellé sans caractère latin. L'appelant DOIT traiter ce cas — un slug vide produit
    « icons/merchants/.png », que listdir_urls filtre comme fichier caché : la vue
    répondrait « logo installé » alors qu'il n'apparaîtra jamais, et tous les marchands
    non latins partageraient le même fichier.
    """
    return slugify(display_name)[:_SLUG_MAX_LENGTH]


@functools.lru_cache(maxsize=2)
def _manual_logo_urls_cached(_ttl_bucket: int) -> dict[str, str]:
    return logos.listdir_urls(MERCHANT_LOGO_PREFIX)


def _manual_logo_urls() -> dict[str, str]:
    ttl_bucket = int(time.monotonic() // _MANUAL_CACHE_TTL_SECONDS)
    return _manual_logo_urls_cached(ttl_bucket)


def clear_manual_logo_cache() -> None:
    _manual_logo_urls_cached.cache_clear()


def _brandfetch_url(domain: str) -> str:
    """
    URL Brandfetch LIVE (hotlink direct navigateur) pour `domain`. "" si pas de
    Client ID configuré (dev sans .env rempli) ou domaine invalide — dégradation
    silencieuse, jamais d'exception (même contrat que le reste du module logos).
    """
    client_id = settings.BRANDFETCH_CLIENT_ID
    if not client_id or not logos.is_valid_domain(domain):
        return ""
    size = _BRANDFETCH_LOGO_SIZE
    return (
        f"{BRANDFETCH_CDN_BASE}/domain/{domain}/theme/light/w/{size}/h/{size}"
        f"/fallback/404/icon.png?c={client_id}"
    )


def get_merchant_logo_map(display_names: list[str]) -> dict[str, str]:
    """
    {display_name: URL ou ""} pour TOUTE une page en 1 scan disque (manuel) +
    N regex (seed, pur Python, pas d'I/O) — pas de N+1 sur une liste de transactions.
    """
    manual = _manual_logo_urls()
    result: dict[str, str] = {}
    for name in set(display_names):
        manual_url = manual.get(slug_for(name))
        if manual_url:
            result[name] = manual_url
            continue
        seed = _match_seed(name)
        result[name] = _brandfetch_url(seed.domain) if seed else ""
    return result


def save_manual_logo(display_name: str, url: str) -> str | None:
    """Installe un logo collé à la main pour CE display_name exact. None si refus/échec."""
    slug = slug_for(display_name)
    if not slug:
        logger.warning(
            "save_manual_logo refusé : display_name=%r produit un slug vide "
            "(aucun caractère latin) — stockage impossible.",
            display_name,
        )
        return None
    name = logos.fetch_from_url(
        url,
        slug,
        prefix=MERCHANT_LOGO_PREFIX,
        on_saved=clear_manual_logo_cache,
    )
    return name
