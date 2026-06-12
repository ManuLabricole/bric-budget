"""
services/logos.py — micro-service : domaine → fichier logo local (Google Favicons).

Contrat :
    is_valid_domain(domain)           — garde anti-injection URL (porté d'update_bank_logos)
    fetch_logo(domain, dest, *, size) — télécharge le logo ; None si échec, ne lève JAMAIS
    has_logo(slug, base_dir)          — un logo existe-t-il déjà pour ce slug ?
    institutions_icon_base()                 — racine static/icons/institutions (seul point Django-aware)

Appelants : accounts (commande backfill_logos + post_save Institution),
transactions.Merchant à venir (#124, qui ajoutera resolve_domain nom → domaine).

Pourquoi « ne lève jamais » : les appelants sont une commande de backfill (un logo
raté ne doit pas stopper les 52 autres) et un post_save (un échec réseau ne doit
jamais faire échouer la sauvegarde d'une Institution). L'échec est loggé, point.

Le primitif réseau est isolé dans _download() — seam de test : les tests le
monkeypatchent, aucun test ne touche le réseau.
"""

from __future__ import annotations

import functools
import logging
import re
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Domaine nu uniquement (minuscules) : lettres/chiffres/points/tirets.
# Refuse scheme, slash, query… → l'URL construite ne peut pas être détournée.
_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$")

# Extensions acceptées comme « logo déjà présent » — alignées sur la résolution
# du tag institution_icon_url (SVG prioritaire, miniature en fallback).
_MINIATURE_EXTS = ("png", "jpg", "jpeg")

DEFAULT_SIZE = 128


def is_valid_domain(domain: str) -> bool:
    """True si `domain` est un domaine nu sûr à interpoler dans une URL."""
    return bool(domain) and _DOMAIN_RE.fullmatch(domain) is not None


def _download(url: str, dest: Path) -> None:
    """Primitif réseau (seam de test). Scheme https hardcodé par l'appelant."""
    urllib.request.urlretrieve(url, dest)  # nosec B310 — domaine validé par regex


def fetch_logo(domain: str, dest: Path, *, size: int = DEFAULT_SIZE) -> Path | None:
    """
    Télécharge le favicon de `domain` vers `dest` (PNG). Retourne dest, ou None si échec.

    Échecs silencieux par contrat (loggés en warning) : domaine invalide, erreur
    réseau, fichier vide (réponse cassée). Aucune exception ne remonte.

    Logs : format clé=valeur STABLE (`logo_fetch <statut> slug=… domain=…`) — base
    d'un futur dashboard de monitoring (quel logo institution/marchand échoue).
    Ne pas reformuler ces messages sans mettre à jour le parsing en face.
    """
    # slug = nom du fichier cible (ex. zkb) — identifiant lisible dans les logs.
    slug = dest.stem

    if not is_valid_domain(domain):
        logger.warning(
            "logo_fetch refused slug=%s domain=%r reason=invalid_domain", slug, domain
        )
        return None

    # L'index favicon de Google ne connaît parfois QUE le www (cas réels :
    # zkb.ch, spirica.fr, societegenerale.fr → 404 nu, 200 en www.) → 2e essai.
    candidates = [domain] if domain.startswith("www.") else [domain, f"www.{domain}"]

    for candidate in candidates:
        url = f"https://www.google.com/s2/favicons?domain={candidate}&sz={size}"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _download(url, dest)
        except Exception as exc:
            logger.warning(
                "logo_fetch failed slug=%s domain=%s candidate=%s reason=download_error error=%r",
                slug,
                domain,
                candidate,
                exc,
            )
            continue

        # Fichier vide = réponse cassée → on nettoie pour ne pas masquer le manque
        # (has_logo le considérerait présent et le backfill ne réessaierait jamais).
        if not dest.is_file() or dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            logger.warning(
                "logo_fetch failed slug=%s domain=%s candidate=%s reason=empty_response",
                slug,
                domain,
                candidate,
            )
            continue

        logger.info(
            "logo_fetch ok slug=%s domain=%s candidate=%s size=%d bytes=%d dest=%s",
            slug,
            domain,
            candidate,
            size,
            dest.stat().st_size,
            dest,
        )
        return dest

    logger.warning(
        "logo_fetch giveup slug=%s domain=%s candidates=%d",
        slug,
        domain,
        len(candidates),
    )
    return None


def has_logo(slug: str, base_dir: Path) -> bool:
    """
    True si un logo existe pour `slug` sous `base_dir` (= static/icons/institutions).

    Même règle que _build_institution_icon_map : svg/<slug>.svg OU miniature/<slug>.{png,jpg,jpeg}.
    """
    if (base_dir / "svg" / f"{slug}.svg").is_file():
        return True
    return any(
        (base_dir / "miniature" / f"{slug}.{ext}").is_file() for ext in _MINIATURE_EXTS
    )


def institutions_icon_base() -> Path:
    """Racine static/icons/institutions — import Django local : le reste du module est pur."""
    from django.conf import settings

    return Path(settings.BASE_DIR) / "static" / "icons" / "institutions"


# =============================================================================
# Résolution slug → URL statique (source UNIQUE, #139)
#
# Deux entrées, une seule logique :
#   - get_institution_icon_map() : batch O(1), 1 scan disque caché → {slug: URL}.
#     Les vues qui résolvent N transactions l'appellent 1× puis font .get() par tx
#     (anti-N+1). lru_cache : les fichiers static ne bougent pas en prod (dev :
#     restart serveur si ajout de logo).
#   - institution_icon_url(obj_or_slug) : unitaire (templates), bâti SUR le map
#     caché → 0 scan disque par appel.
#
# ⛔ has_logo() ne passe PAS par ce cache : c'est le write-path (backfill écrit les
#    fichiers), un map caché y serait périmé. Garder son check disque frais.
# =============================================================================

# Priorité d'extension dans miniature/ (PNG > JPG > JPEG si un même slug a plusieurs
# fichiers). Pas de "svg" ici : le SVG vit dans svg/ et écrase toujours en aval.
_MINIATURE_PRIORITY = {"png": 0, "jpg": 1, "jpeg": 2}


@functools.lru_cache(maxsize=None)
def get_institution_icon_map() -> dict[str, str]:
    """Accesseur caché du map {slug → URL statique}. SVG prioritaire sur miniature."""
    return _build_institution_icon_map()


def _build_institution_icon_map() -> dict[str, str]:
    """
    Scan disque pur (svg/ + miniature/) → dict. Séparé du cache pour être
    instrumentable par les tests (preuve anti-N+1 : N résolutions → 1 build).

    Retourne {} si les dossiers n'existent pas (ex. tests sans static).
    """
    from django.templatetags.static import static

    base = institutions_icon_base()
    svg_dir = base / "svg"
    miniature_dir = base / "miniature"

    result: dict[str, str] = {}

    # Miniatures (fallback) : meilleure extension par slug.
    if miniature_dir.exists():
        best: dict[str, tuple[int, str]] = {}
        for f in miniature_dir.iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            prio = _MINIATURE_PRIORITY.get(f.suffix.lstrip(".").lower(), 99)
            if f.stem not in best or prio < best[f.stem][0]:
                best[f.stem] = (prio, f.name)
        result = {
            slug: static(f"icons/institutions/miniature/{fname}")
            for slug, (_, fname) in best.items()
        }

    # SVG : priorité absolue (paths purs, currentColor, pas de fond) → écrase la miniature.
    if svg_dir.exists():
        for f in svg_dir.iterdir():
            if (
                f.is_file()
                and not f.name.startswith(".")
                and f.suffix.lower() == ".svg"
            ):
                result[f.stem] = static(f"icons/institutions/svg/{f.name}")

    return result


def _coerce_slug(institution_or_slug) -> str:
    """Objet Institution (icon_slug prioritaire → slug) ou chaîne slug → slug nu."""
    obj = institution_or_slug
    if hasattr(obj, "icon_slug"):
        return str(obj.icon_slug or getattr(obj, "slug", ""))
    if hasattr(obj, "slug"):
        return str(obj.slug)
    return str(obj)


def institution_icon_url(institution_or_slug) -> str:
    """
    URL statique du logo pour une institution (objet ou slug), ou "" si absent.

    Unitaire — bâti sur le map caché → 0 scan disque par appel. Destiné aux
    templates (faible volume) ; les vues à fort volume utilisent get_institution_icon_map().
    """
    return get_institution_icon_map().get(_coerce_slug(institution_or_slug), "")
