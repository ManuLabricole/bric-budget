"""
transactions/templatetags/budget_filters.py

Filtres de formatage pour la page Budget.

Pourquoi un template filter et pas du Python inline ?
    Le formatage monétaire est appliqué sur ~15 montants dans le template.
    Le dupliquer inline avec replace() partout serait illisible.
    Un filter nommé `chf` est self-documenting et testé en un seul endroit.

Usage dans les templates :
    {% load budget_filters %}
    {{ total_income|chf }}          → "32 232"   (0 décimales, séparateur espace)
    {{ total_income|chf_dec }}      → "32 232,50" (2 décimales, virgule)

Convention de signe : ces filtres retournent toujours la valeur ABSOLUE.
Le signe (+ ou −) est ajouté dans le template selon le contexte.

Exemple complet :
    −{{ total_expenses_abs|chf }} CHF  →  −29 923 CHF
    +{{ total_income|chf }} CHF        →  +32 232 CHF
"""

from django import template

register = template.Library()


def _format_amount(value, decimal_places):
    """
    Convertit un nombre en string formaté :
    - Séparateur de milliers : espace insécable étroit (U+202F) — typographie FR correcte
    - Séparateur décimal : virgule
    - Toujours en valeur absolue — le signe est géré dans le template

    Technique :
        f"{1234567.89:,.2f}" → "1,234,567.89"  (format Python avec virgule thousands)
        .replace(",", "\u202f")                 → "1\u202f234\u202f567.89" (espace)
        .replace(".", ",")                      → "1\u202f234\u202f567,89" (virgule décimale)
    """
    try:
        v = abs(float(value))
        formatted = f"{v:,.{decimal_places}f}"
        # Remplacement en deux passes : virgules des milliers → espace, point → virgule
        formatted = formatted.replace(",", "\u202f")  # espace insécable étroit
        if decimal_places > 0:
            formatted = formatted.replace(".", ",")
        return formatted
    except (TypeError, ValueError):
        return str(value)


@register.filter
def chf(value):
    """Format monétaire sans décimales : 32232 → "32 232"."""
    return _format_amount(value, decimal_places=0)


@register.filter
def chf_dec(value):
    """Format monétaire avec 2 décimales : 32232.5 → "32 232,50"."""
    return _format_amount(value, decimal_places=2)


# ── Gauge demi-cercle SVG ──────────────────────────────────────────────────────
# Demi-périmètre = π × r = π × 40 = 125.66 (r=40 dans le viewBox 100×52).

GAUGE_HALF_PERIMETER = 125.66
GAUGE_COLOR_INCOME = "#4dbf93"  # même valeur que le token Tailwind "income"
GAUGE_COLOR_WARNING = "#f97316"  # même valeur que le token Tailwind "warning"


@register.filter
def gauge_fill(pct):
    """Convertit un pourcentage (0–200+) en longueur d'arc SVG (0–125.66).
    Plafonné à 100% = arc complet.
    Usage : {{ target_pct|gauge_fill }}
    """
    try:
        return round(min(float(pct), 100) / 100 * GAUGE_HALF_PERIMETER, 1)
    except (TypeError, ValueError):
        return 0


@register.filter
def gauge_color(pct, threshold=100):
    """Retourne la couleur hex income si pct <= threshold, warning sinon.
    Usage : {{ target_pct|gauge_color }}          → vert si ≤ 100
            {{ over_pct|gauge_color:0 }}           → vert si = 0
    """
    try:
        return (
            GAUGE_COLOR_INCOME
            if float(pct) <= float(threshold)
            else GAUGE_COLOR_WARNING
        )
    except (TypeError, ValueError):
        return GAUGE_COLOR_INCOME
