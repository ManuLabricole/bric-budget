"""accounts/iban.py — normalisation canonique d'un IBAN saisi.

L'IBAN (`Account.iban`) est LA clé de rattachement des imports
(`connectors/resolver.py`). Toute saisie/édition — wizard de création, formulaire
d'édition panel, crayon inline — DOIT le normaliser de façon IDENTIQUE, sinon deux
représentations du même IBAN ne matchent pas. Centralisé ici, dans l'app
propriétaire du champ (convention « data/logique d'app dans l'app », #126).
"""

from __future__ import annotations


def normalize_iban(raw: str) -> str:
    """IBAN saisi → sans AUCUN blanc + majuscules.

    `str.split()` (sans argument) avale TOUS les espaces unicode (insécable A0,
    fine 202F...) que les banques/macOS glissent dans un IBAN copié-collé — un
    `replace(" ", "")` ne retire que l'espace ASCII et laisserait un IBAN malformé
    qui casse le matching d'import.
    """
    return "".join(raw.split()).upper()
