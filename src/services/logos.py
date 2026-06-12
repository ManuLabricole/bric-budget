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
import ipaddress
import logging
import re
import time
import urllib.error
import urllib.parse
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

# ── Réparation manuelle par URL (#128) ───────────────────────────────────────
# Extension dérivée du CONTENT-TYPE, jamais de l'URL. SVG accepté (les meilleurs logos
# de marque sont vectoriels) MAIS un SVG est du XML qui peut embarquer du script →
# garde anti-XSS _is_safe_svg() avant stockage. Rendu toujours via <img> (le navigateur
# n'exécute pas le script d'un SVG chargé en <img>), et en prod servi depuis l'origine
# du bucket (distincte de l'app) → surface XSS résiduelle quasi nulle.
_ALLOWED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}
_MAX_LOGO_BYTES = 512 * 1024
# Motifs interdits dans un SVG uploadé (script, handlers inline, refs externes).
# Heuristique de défense en profondeur (la vraie barrière = rendu <img> + origine bucket
# distincte), PAS une sanitisation XML complète. `[\s/]on\w+` couvre `<svg/onload=` (pas
# d'espace). Vecteurs encodés (entités HTML, CDATA) non couverts → durcissement = lib dédiée.
_SVG_UNSAFE_RE = re.compile(
    rb"<script|javascript:|<foreignObject|[\s/]on\w+\s*=", re.IGNORECASE
)
# Chemin DANS le storage MEDIA par défaut (mediafiles/ en dev, bucket Railway en prod).
_REPAIRED_LOGO_PREFIX = "icons/institutions"


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

# TTL du cache du map (anti-N+1 sur une fenêtre courte). DOIT rester < à l'expiration
# des URLs présignées du bucket privé (querystring_expire, 1h par défaut) : sinon une
# URL présignée mise en cache expirerait avant d'être rafraîchie → logo cassé en prod.
_ICON_MAP_TTL_SECONDS = 600


@functools.lru_cache(maxsize=2)
def _icon_map_cached(_ttl_bucket: int) -> dict[str, str]:
    """Map mis en cache par fenêtre de TTL (la clé _ttl_bucket force le rebuild à expiration)."""
    return _build_institution_icon_map()


def get_institution_icon_map() -> dict[str, str]:
    """
    Accesseur du map {slug → URL}. Cache à TTL court (~10 min) : 1 seul scan par fenêtre
    (anti-N+1) tout en rafraîchissant les URLs présignées du bucket avant leur expiration.
    SVG prioritaire sur logo réparé, lui-même prioritaire sur miniature.
    """
    ttl_bucket = int(time.monotonic() // _ICON_MAP_TTL_SECONDS)
    return _icon_map_cached(ttl_bucket)


def clear_institution_icon_cache() -> None:
    """Invalide le cache du map (après installation d'un logo réparé, et dans les tests)."""
    _icon_map_cached.cache_clear()


def _build_institution_icon_map() -> dict[str, str]:
    """
    Scan disque pur (svg/ + miniature/) → dict. Séparé du cache pour être
    instrumentable par les tests (preuve anti-N+1 : N résolutions → 1 build).

    Retourne {} si les dossiers n'existent pas (ex. tests sans static).

    Priorité de résolution (du plus faible au plus fort) :
        miniature (static) < logo réparé (MEDIA #128) < SVG (static, curé en git).
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

    # Logos réparés à chaud (#128) : bucket S3 en prod, mediafiles/ en dev. Battent le
    # favicon auto (miniature), pas le SVG curé. listdir = 1 appel storage (lru_cache amont).
    for stem, url in _repaired_logo_urls().items():
        result[stem] = url

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


def _repaired_logo_urls() -> dict[str, str]:
    """
    {slug: URL} des logos réparés à chaud, lus depuis le storage MEDIA par défaut
    (bucket S3 en prod, mediafiles/ en dev). 1 listdir par build (mis en cache amont).

    Tolère un storage non provisionné (dev sans mediafiles/, prod sans bucket) →
    retourne {} plutôt que d'échouer la résolution (fallback statique préservé).
    """
    from django.core.files.storage import default_storage

    try:
        _dirs, files = default_storage.listdir(_REPAIRED_LOGO_PREFIX)
    except Exception as exc:
        # Storage non provisionné (FileNotFoundError) OU erreur réseau/auth S3
        # (botocore.ClientError, qui n'hérite PAS d'OSError) → ne JAMAIS faire planter
        # la résolution de TOUS les logos (y compris statiques). Fallback statique préservé.
        logger.warning("repaired_logo_urls unavailable reason=%r", exc)
        return {}

    urls: dict[str, str] = {}
    for fname in files:
        if fname.startswith(".") or "." not in fname:
            continue
        stem = fname.rsplit(".", 1)[0]
        urls[stem] = default_storage.url(f"{_REPAIRED_LOGO_PREFIX}/{fname}")
    return urls


# =============================================================================
# Réparation manuelle d'un logo par URL (#128)
# =============================================================================


def _is_safe_host(host: str | None) -> bool:
    """
    Garde anti-SSRF : n'autorise qu'un nom de domaine public.

    Refuse vide, IP littérale (métadonnées cloud 169.254.169.254, réseaux privés…),
    localhost et suffixes internes. Limite connue (v1) : une URL dont le hostname
    résout vers une IP privée (DNS rebinding) passe — risque accepté pour une vue
    login_required mono-utilisateur ; à durcir si exposition multi-tenant.
    """
    if not host:
        return False
    host = host.lower()
    if host == "localhost" or host.endswith((".internal", ".local", ".localhost")):
        return False
    try:
        ipaddress.ip_address(host)
        return False  # IP littérale → toujours refusée (on ne veut que des domaines)
    except ValueError:
        return True  # pas une IP → hostname, accepté


def _is_safe_svg(data: bytes) -> bool:
    """
    Garde anti-XSS pour un SVG uploadé : rejette script, handlers inline (onload=…),
    javascript: et <foreignObject>. Heuristique volontairement stricte (un faux positif
    = l'utilisateur reprend un autre fichier), PAS une sanitisation XML complète.
    """
    return _SVG_UNSAFE_RE.search(data) is None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Refuse de suivre les redirections 30x. Sans ça, `_is_safe_host()` (qui ne valide
    QUE l'URL initiale) serait contournée : un `https://evil/logo.png` répondant
    `302 → http://169.254.169.254/…` ferait fetcher une cible interne par le serveur
    (SSRF, OWASP A10). Toute redirection lève une HTTPError, attrapée par fetch_from_url.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, f"redirect refusé (anti-SSRF): {newurl}", headers, fp
        )


# Opener sans suivi de redirect (anti-SSRF) — réutilisé par _download_url.
_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler)


def _download_url(url: str) -> tuple[bytes, str]:
    """
    Primitif réseau (seam de test). Retourne (contenu, content_type).

    Lit au plus _MAX_LOGO_BYTES + 1 octets → le dépassement est détecté par l'appelant
    sans charger un fichier géant en mémoire. Scheme https + host validés EN AMONT par
    fetch_from_url ; les redirections sont REFUSÉES (anti-SSRF, cf. _NoRedirectHandler).
    """
    req = urllib.request.Request(url, headers={"User-Agent": "BricBudget/1.0"})
    # nosec B310 — scheme https validé amont + redirects désactivés (pas de file://, pas de hop interne).
    with _no_redirect_opener.open(req, timeout=10) as resp:
        return resp.read(_MAX_LOGO_BYTES + 1), resp.headers.get_content_type()


def fetch_from_url(url: str, slug: str) -> str | None:
    """
    Installe un logo depuis une URL collée à la main → storage MEDIA par défaut.

    Retourne le nom stocké (relatif au storage) ou None si refus/échec. Contrat
    « ne lève JAMAIS » (comme fetch_logo) — tout chemin de sortie est loggé.

    Gardes : https only + host non-IP/non-interne + redirects refusés (SSRF),
    content-type raster OU svg whitelisté, réponse non vide, taille ≤ 512 Ko, et
    garde anti-XSS sur tout corps qui RESSEMBLE à du SVG (indépendamment du
    content-type déclaré → anti-spoof). Logs : format STABLE `logo_fetch <statut>
    slug=… source=manual_url …` (dashboard).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not _is_safe_host(parsed.hostname):
        logger.warning(
            "logo_fetch refused slug=%s source=manual_url reason=unsafe_url url=%r",
            slug,
            url,
        )
        return None

    try:
        data, content_type = _download_url(url)
    except Exception as exc:
        logger.warning(
            "logo_fetch failed slug=%s source=manual_url reason=download_error error=%r",
            slug,
            exc,
        )
        return None

    ext = _ALLOWED_IMAGE_TYPES.get(content_type)
    if ext is None:
        logger.warning(
            "logo_fetch refused slug=%s source=manual_url reason=bad_content_type content_type=%s",
            slug,
            content_type,
        )
        return None
    if not data:
        logger.warning(
            "logo_fetch failed slug=%s source=manual_url reason=empty_response", slug
        )
        return None
    if len(data) > _MAX_LOGO_BYTES:
        logger.warning(
            "logo_fetch refused slug=%s source=manual_url reason=too_large bytes=%d",
            slug,
            len(data),
        )
        return None
    # Détection de contenu SVG INDÉPENDANTE du content-type déclaré (anti-spoof : un
    # serveur peut annoncer image/png et servir un SVG avec script). Si le corps ressemble
    # à du SVG/XML, on impose la garde anti-XSS et on force l'extension .svg.
    if data[:512].lstrip().lower().startswith((b"<?xml", b"<svg")):
        if not _is_safe_svg(data):
            logger.warning(
                "logo_fetch refused slug=%s source=manual_url reason=unsafe_svg", slug
            )
            return None
        ext = "svg"

    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    # Un seul fichier réparé par slug : purger les variantes d'extension avant d'écrire
    # (sinon zkb.png + zkb.webp coexistent et S3 ne remplace pas — il suffixe le nom).
    for old_ext in _ALLOWED_IMAGE_TYPES.values():
        old_name = f"{_REPAIRED_LOGO_PREFIX}/{slug}.{old_ext}"
        if default_storage.exists(old_name):
            default_storage.delete(old_name)

    saved = default_storage.save(
        f"{_REPAIRED_LOGO_PREFIX}/{slug}.{ext}", ContentFile(data)
    )
    # Le map est en cache → sans invalidation, le logo n'apparaîtrait qu'à l'expiration du TTL.
    clear_institution_icon_cache()
    logger.info(
        "logo_fetch ok slug=%s source=manual_url bytes=%d name=%s",
        slug,
        len(data),
        saved,
    )
    return saved
