"""
accounts/banks_config.py — Source de vérité pour les banques supportées.

Pourquoi un fichier de config plutôt qu'un fixture Django ?
------------------------------------------------------------
Un fixture est un snapshot de la DB à un instant T — il peut désynchroniser
si la DB évolue. Ce fichier est du code Python : on le lit, on fait get_or_create,
et la DB reste toujours en phase avec la config.

Ajouter une nouvelle banque
---------------------------
1. Ajouter une entrée dans KNOWN_BANKS (slug = clé du dict)
2. Déposer l'icône dans static/icons/banks/miniature/<slug>.png
3. Lancer : python manage.py seed_banks
4. Ajouter le connecteur dans connectors/resolver.py si un export existe

Structure de chaque entrée
--------------------------
  name     : nom affiché dans l'UI
  currency : devise principale (ISO 4217) — utilisée comme défaut à la création de compte
  bic      : BIC/SWIFT de la banque (pas du compte) — pré-rempli sur les CheckingAccounts
  country  : code pays ISO 3166-1 alpha-2
"""

KNOWN_BANKS = {
    "yuh": {
        "name": "Yuh",
        "currency": "CHF",
        "bic": "YUHHCHZZ",
        "country": "CH",
    },
    "ubs": {
        "name": "UBS",
        "currency": "CHF",
        "bic": "UBSWCHZH80A",
        "country": "CH",
    },
    "cic": {
        "name": "CIC",
        "currency": "EUR",
        "bic": "CMCIFRPP",
        "country": "FR",
    },
    "boursorama": {
        "name": "Boursorama",
        "currency": "EUR",
        "bic": "BOUSFRPPXXX",
        "country": "FR",
    },
    "finpension": {
        "name": "Finpension",
        "currency": "CHF",
        "bic": "",
        "country": "CH",
    },
}
