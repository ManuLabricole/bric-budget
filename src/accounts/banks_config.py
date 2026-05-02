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
  country  : code pays ISO 3166-1 alpha-2

Note : pas de BIC ici — le BIC est propre à chaque compte (CheckingAccount.bic),
pas à la banque. Il est saisi manuellement via seed_accounts ou l'admin Django.
"""

KNOWN_BANKS = {
    "yuh": {
        "name": "Yuh",
        "currency": "CHF",
        "country": "CH",
    },
    "ubs": {
        "name": "UBS",
        "currency": "CHF",
        "country": "CH",
    },
    "cic": {
        "name": "CIC",
        "currency": "EUR",
        "country": "FR",
    },
    "boursorama": {
        "name": "Boursorama",
        "currency": "EUR",
        "country": "FR",
    },
    "finpension": {
        "name": "Finpension",
        "currency": "CHF",
        "country": "CH",
    },
}
