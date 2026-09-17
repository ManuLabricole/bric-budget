"""
services/merchant_logos.py — display_name → logo (seed connu + ajout manuel).

Deux couches, key-spaces disjoints (pas de collision possible) :
  - SEED (committé, STATIC) : mot-clé régulier → marque connue, résolu par
    resolve_seed_key() contre transactions/reference/merchant_seed.json. Fichier
    servi depuis static/icons/merchants/<key>.png (déployé par collectstatic —
    jamais écrit à l'exécution, alimenté par la commande prototype_merchant_logos).
  - MANUEL (runtime, MEDIA) : l'utilisateur colle une URL pour UN display_name
    précis (bouton badge sur une transaction) → stocké sous
    icons/merchants/<slugify(display_name)>.<ext> dans le storage MEDIA par
    défaut (bucket S3 en prod), via services.logos.fetch_from_url — même
    primitif que la réparation de logo institution (#128). Gagne TOUJOURS sur
    le seed (action utilisateur explicite).

Limite assumée (#124 — pas de modèle Merchant dans ce lot) : la clé manuelle est
le display_name EXACT, pas un alias flou. Deux variantes textuelles du même
marchand réel exigent 2 ajouts manuels distincts — acceptable en v1 (YAGNI),
résolu proprement plus tard par un vrai modèle Merchant/MerchantAlias si le
besoin se confirme.

Appelant à fort volume (liste de transactions) : get_merchant_logo_map(names)
résout tout en 1 scan disque (manuel, mis en cache) + 1 passage regex par nom
distinct (seed) — jamais de N+1 (même principe que get_institution_icon_map).

NOTE fuzzy : le prototype (management command) a mesuré rapidfuzz en tier de
secours et trouvé un faux positif net ("PARKING" → APCOA Parking, score 100 en
token_set_ratio dès qu'un mot générique est un sous-ensemble de tokens de
l'autre côté). Le fuzzy reste un outil d'EXPLORATION CLI — jamais branché ici,
en résolution live.
"""

from __future__ import annotations

import functools
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.templatetags.static import static as static_url
from django.utils.text import slugify

from services import logos

SEED_PATH = (
    Path(__file__).resolve().parent.parent
    / "transactions"
    / "reference"
    / "merchant_seed.json"
)
MERCHANT_LOGO_PREFIX = "icons/merchants"
_MANUAL_CACHE_TTL_SECONDS = 600
_SLUG_MAX_LENGTH = 80


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
        alternation = "|".join(re.escape(kw) for kw in entry["keywords"])
        pattern = re.compile(rf"\b(?:{alternation})")
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


def resolve_seed_key(display_name: str) -> str | None:
    """Premier seed dont un mot-clé apparaît (frontières de mots) — ordre = priorité."""
    normalized = normalize(display_name)
    for seed in load_seed():
        if seed.pattern.search(normalized):
            return seed.key
    return None


def slug_for(display_name: str) -> str:
    return slugify(display_name)[:_SLUG_MAX_LENGTH]


@functools.lru_cache(maxsize=2)
def _manual_logo_urls_cached(_ttl_bucket: int) -> dict[str, str]:
    return logos.listdir_urls(MERCHANT_LOGO_PREFIX)


def _manual_logo_urls() -> dict[str, str]:
    ttl_bucket = int(time.monotonic() // _MANUAL_CACHE_TTL_SECONDS)
    return _manual_logo_urls_cached(ttl_bucket)


def clear_manual_logo_cache() -> None:
    _manual_logo_urls_cached.cache_clear()


def _seed_logo_static_dir() -> Path:
    """Racine static/icons/merchants — même pattern que logos.institutions_icon_base()."""
    return Path(settings.BASE_DIR) / "static" / "icons" / "merchants"


def _seed_logo_url(seed_key: str) -> str:
    """
    URL statique résolue via le tag {% static %} (django.templatetags.static.static),
    PAS une concaténation de string : en prod STATICFILES_STORAGE est un
    CompressedManifestStaticFilesStorage (WhiteNoise) qui renomme chaque fichier avec
    un hash de contenu (`decathlon.a1b2c3.png`) — une URL construite à la main serait
    un 404 silencieux en prod alors qu'elle marche en dev (DEBUG=True, pas de manifest).

    Vérifie D'ABORD que le fichier existe sur disque (le seed JSON peut lister une
    entrée dont le logo n'a pas encore été récupéré via prototype_merchant_logos) —
    un fichier absent du manifest fait lever ValueError côté Django, donc on ne
    tente static() que si le fichier source est bien là.
    """
    if not (_seed_logo_static_dir() / f"{seed_key}.png").is_file():
        return ""
    return static_url(f"icons/merchants/{seed_key}.png")


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
        seed_key = resolve_seed_key(name)
        result[name] = _seed_logo_url(seed_key) if seed_key else ""
    return result


def save_manual_logo(display_name: str, url: str) -> str | None:
    """Installe un logo collé à la main pour CE display_name exact. None si refus/échec."""
    name = logos.fetch_from_url(
        url,
        slug_for(display_name),
        prefix=MERCHANT_LOGO_PREFIX,
        on_saved=clear_manual_logo_cache,
    )
    return name
