"""
tests/security/test_no_runtime_cdn.py

⛔ Verrou anti-régression : aucun CDN runtime non-pinné dans les templates.

Pourquoi :
    Un script servi depuis un CDN (cdn.tailwindcss.com, unpkg.com) peut être
    modifié par un attaquant qui compromet le CDN. Le navigateur exécute le code
    avec les permissions de notre origin (accès aux cookies, formulaires, etc.).

Mitigations acceptées :
    - SRI hash (`integrity="sha384-..."`) : le navigateur refuse si le fichier est modifié
    - Build statique local + collectstatic + servi par whitenoise
    - Marqueur explicite `<!-- allow-cdn: <raison> -->` (à utiliser avec parcimonie)

Si ce test échoue :
    1. Migrer le script en local (download + collectstatic), OU
    2. Ajouter un `integrity="sha384-..."` après calcul du hash, OU
    3. Annoter avec `<!-- allow-cdn: justification -->` si exception légitime
"""

import re
from pathlib import Path

import pytest

# Patterns de CDN connus interdits sans SRI.
FORBIDDEN_CDN_PATTERNS = [
    r"https?://cdn\.tailwindcss\.com",
    r"https?://unpkg\.com",
    r"https?://cdnjs\.cloudflare\.com",
    r"https?://cdn\.jsdelivr\.net",
    r"https?://maxcdn\.bootstrapcdn\.com",
]

# Le marqueur d'exception explicite : `<!-- allow-cdn: raison -->`
ALLOW_CDN_RE = re.compile(r"<!--\s*allow-cdn:\s*([^\-]+)\s*-->")

# Pattern qui détecte un attribut integrity sur la même ligne ou les 2 suivantes.
INTEGRITY_RE = re.compile(r'integrity\s*=\s*"sha\d+-')


def _scan_template_files() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[3]
    templates = repo_root / "src" / "templates"
    return list(templates.rglob("*.html"))


def _line_is_protected(lines: list[str], idx: int) -> bool:
    """Une ligne avec CDN est OK si SRI sur cette ligne ou les 3 suivantes,
    ou si un commentaire `allow-cdn` est posé dans le bloc juste au-dessus."""
    # SRI check sur la fenêtre [idx, idx+3]
    window = "".join(lines[idx : idx + 4])
    if INTEGRITY_RE.search(window):
        return True
    # allow-cdn dans les 3 lignes précédentes
    above = "".join(lines[max(0, idx - 3) : idx])
    return bool(ALLOW_CDN_RE.search(above))


@pytest.mark.parametrize("pattern", FORBIDDEN_CDN_PATTERNS)
def test_no_unprotected_cdn_in_templates(pattern):
    """Aucun CDN runtime non protégé (SRI absent, pas de marker allow-cdn)."""
    regex = re.compile(pattern)
    offending = []
    for tpl in _scan_template_files():
        lines = tpl.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            if regex.search(line) and not _line_is_protected(lines, i):
                offending.append(f"{tpl}:{i + 1}: {line.rstrip()}")
    assert not offending, (
        "CDN non protégé détecté dans les templates. Soit ajoute un SRI hash, soit\n"
        "migre en build local, soit annote avec `<!-- allow-cdn: <raison> -->`.\n"
        + "\n".join(offending)
    )
