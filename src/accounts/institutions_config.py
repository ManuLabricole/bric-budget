"""
accounts/institutions_config.py — Source de vérité pour les institutions supportées.

Pourquoi un fichier de config plutôt qu'un fixture Django ?
------------------------------------------------------------
Un fixture est un snapshot de la DB à un instant T — il peut désynchroniser
si la DB évolue. Ce fichier est du code Python : on le lit, on fait get_or_create,
et la DB reste toujours en phase avec la config.

Ajouter une nouvelle institution
--------------------------------
1. Ajouter une entrée dans KNOWN_INSTITUTIONS (slug = clé du dict)
2. Lancer : python manage.py seed_banks
   → le logo est récupéré automatiquement via `domain` (post_save Institution,
     service services/logos.py). Rattrapage : python manage.py backfill_logos.
   → si le logo Google Favicons est moche/générique : déposer un SVG manuel dans
     static/icons/banks/svg/<slug>.svg (prioritaire sur le PNG).
3. Ajouter le connecteur dans connectors/resolver.py si un export existe

Structure de chaque entrée
--------------------------
  name     : nom affiché dans l'UI
  currency : devise principale (ISO 4217) — défaut à la création de compte
  country  : code pays ISO 3166-1 alpha-2
  domain   : domaine web nu (minuscules, sans scheme) — récupération du logo

Notes
-----
- Pas de BIC ici — le BIC est propre à chaque compte (CheckingAccount.bic),
  pas à l'institution.
- Courtiers/distributeurs AV (Boursorama, Meilleurtaux, Linxea) ET assureurs
  (Generali, Spirica…) sont DEUX types d'entrées distincts : pour une assurance
  vie, Account.institution = le courtier (là où l'user se connecte) ; l'assureur
  sous-jacent sera un champ séparé (futur LifeInsuranceDetails.insurer).
"""

KNOWN_INSTITUTIONS = {
    # ── Banques de détail — Suisse ────────────────────────────────────────────
    "ubs": {
        "name": "UBS",
        "currency": "CHF",
        "country": "CH",
        "domain": "ubs.com",
    },
    "postfinance": {
        "name": "PostFinance",
        "currency": "CHF",
        "country": "CH",
        "domain": "postfinance.ch",
    },
    "raiffeisen": {
        "name": "Raiffeisen",
        "currency": "CHF",
        "country": "CH",
        "domain": "raiffeisen.ch",
    },
    "migros-bank": {
        "name": "Migros Bank",
        "currency": "CHF",
        "country": "CH",
        "domain": "migrosbank.ch",
    },
    "bcv": {
        "name": "Banque Cantonale Vaudoise",
        "currency": "CHF",
        "country": "CH",
        "domain": "bcv.ch",
    },
    "bcge": {
        "name": "Banque Cantonale de Genève",
        "currency": "CHF",
        "country": "CH",
        "domain": "bcge.ch",
    },
    "zkb": {
        "name": "Zürcher Kantonalbank",
        "currency": "CHF",
        "country": "CH",
        "domain": "zkb.ch",
    },
    "valiant": {
        "name": "Valiant",
        "currency": "CHF",
        "country": "CH",
        "domain": "valiant.ch",
    },
    "bank-cler": {
        "name": "Bank Cler",
        "currency": "CHF",
        "country": "CH",
        "domain": "cler.ch",
    },
    # ── Néobanques — Suisse ───────────────────────────────────────────────────
    "yuh": {
        "name": "Yuh",
        "currency": "CHF",
        "country": "CH",
        "domain": "yuh.ch",
    },
    "neon": {
        "name": "Neon",
        "currency": "CHF",
        "country": "CH",
        "domain": "neon-free.ch",
    },
    "alpian": {
        "name": "Alpian",
        "currency": "CHF",
        "country": "CH",
        "domain": "alpian.com",
    },
    "radicant": {
        "name": "Radicant",
        "currency": "CHF",
        "country": "CH",
        "domain": "radicant.com",
    },
    # ── Banques de détail — France ────────────────────────────────────────────
    "bnp-paribas": {
        "name": "BNP Paribas",
        "currency": "EUR",
        "country": "FR",
        # group.bnpparibas : seul domaine BNP avec un favicon 128px dans l'index
        # Google (mabanque.bnpparibas → 16px seulement).
        "domain": "group.bnpparibas",
    },
    "credit-agricole": {
        "name": "Crédit Agricole",
        "currency": "EUR",
        "country": "FR",
        "domain": "credit-agricole.fr",
    },
    "societe-generale": {
        "name": "Société Générale",
        "currency": "EUR",
        "country": "FR",
        "domain": "societegenerale.fr",
    },
    "caisse-epargne": {
        "name": "Caisse d'Épargne",
        "currency": "EUR",
        "country": "FR",
        "domain": "caisse-epargne.fr",
    },
    "banque-populaire": {
        "name": "Banque Populaire",
        "currency": "EUR",
        "country": "FR",
        "domain": "banquepopulaire.fr",
    },
    "lcl": {
        "name": "LCL",
        "currency": "EUR",
        "country": "FR",
        "domain": "lcl.fr",
    },
    "cic": {
        "name": "CIC",
        "currency": "EUR",
        "country": "FR",
        "domain": "cic.fr",
    },
    "credit-mutuel": {
        "name": "Crédit Mutuel",
        "currency": "EUR",
        "country": "FR",
        "domain": "creditmutuel.fr",
    },
    "la-banque-postale": {
        "name": "La Banque Postale",
        "currency": "EUR",
        "country": "FR",
        "domain": "labanquepostale.fr",
    },
    "ccf": {
        "name": "CCF",
        "currency": "EUR",
        "country": "FR",
        "domain": "ccf.fr",
    },
    # ── Néobanques / banques en ligne — France & Europe ──────────────────────
    "boursorama": {
        "name": "BoursoBank",
        "currency": "EUR",
        "country": "FR",
        "domain": "boursobank.com",
    },
    "fortuneo": {
        "name": "Fortuneo",
        "currency": "EUR",
        "country": "FR",
        "domain": "fortuneo.fr",
    },
    "monabanq": {
        "name": "Monabanq",
        "currency": "EUR",
        "country": "FR",
        "domain": "monabanq.com",
    },
    "hello-bank": {
        "name": "Hello bank!",
        "currency": "EUR",
        "country": "FR",
        "domain": "hellobank.fr",
    },
    "bforbank": {
        "name": "BforBank",
        "currency": "EUR",
        "country": "FR",
        "domain": "bforbank.com",
    },
    "nickel": {
        "name": "Nickel",
        "currency": "EUR",
        "country": "FR",
        "domain": "nickel.eu",
    },
    "n26": {
        "name": "N26",
        "currency": "EUR",
        "country": "DE",
        "domain": "n26.com",
    },
    "revolut": {
        "name": "Revolut",
        "currency": "EUR",
        "country": "GB",
        "domain": "revolut.com",
    },
    "lydia": {
        "name": "Lydia",
        "currency": "EUR",
        "country": "FR",
        "domain": "lydia-app.com",
    },
    "wise": {
        "name": "Wise",
        "currency": "EUR",
        "country": "GB",
        "domain": "wise.com",
    },
    # ── Courtiers / investissement ────────────────────────────────────────────
    "swissquote": {
        "name": "Swissquote",
        "currency": "CHF",
        "country": "CH",
        "domain": "swissquote.ch",
    },
    "saxo": {
        "name": "Saxo Bank",
        "currency": "EUR",
        "country": "DK",
        "domain": "home.saxo",
    },
    "interactive-brokers": {
        "name": "Interactive Brokers",
        "currency": "USD",
        "country": "US",
        "domain": "interactivebrokers.com",
    },
    "degiro": {
        "name": "DEGIRO",
        "currency": "EUR",
        "country": "NL",
        "domain": "degiro.com",
    },
    "trade-republic": {
        "name": "Trade Republic",
        "currency": "EUR",
        "country": "DE",
        "domain": "traderepublic.com",
    },
    "scalable-capital": {
        "name": "Scalable Capital",
        "currency": "EUR",
        "country": "DE",
        "domain": "scalable.capital",
    },
    "etoro": {
        "name": "eToro",
        "currency": "USD",
        "country": "IL",
        "domain": "etoro.com",
    },
    "bourse-direct": {
        "name": "Bourse Direct",
        "currency": "EUR",
        "country": "FR",
        "domain": "boursedirect.fr",
    },
    # ── Prévoyance 3a / LPP — Suisse ──────────────────────────────────────────
    "finpension": {
        "name": "Finpension",
        "currency": "CHF",
        "country": "CH",
        "domain": "finpension.ch",
    },
    "viac": {
        "name": "VIAC",
        "currency": "CHF",
        "country": "CH",
        "domain": "viac.ch",
    },
    "frankly": {
        "name": "frankly",
        "currency": "CHF",
        "country": "CH",
        "domain": "frankly.ch",
    },
    "selma": {
        "name": "Selma",
        "currency": "CHF",
        "country": "CH",
        "domain": "selma.com",
    },
    # ── Crypto (exchanges) ────────────────────────────────────────────────────
    "binance": {
        "name": "Binance",
        "currency": "EUR",
        "country": "MT",
        "domain": "binance.com",
    },
    "kraken": {
        "name": "Kraken",
        "currency": "USD",
        "country": "US",
        "domain": "kraken.com",
    },
    "coinbase": {
        "name": "Coinbase",
        "currency": "USD",
        "country": "US",
        "domain": "coinbase.com",
    },
    "relai": {
        "name": "Relai",
        "currency": "CHF",
        "country": "CH",
        "domain": "relai.app",
    },
    # ── Assurance vie — assureurs ─────────────────────────────────────────────
    "spirica": {
        "name": "Spirica",
        "currency": "EUR",
        "country": "FR",
        "domain": "spirica.fr",
    },
    "swiss-life": {
        "name": "Swiss Life",
        "currency": "CHF",
        "country": "CH",
        "domain": "swisslife.ch",
    },
    "generali": {
        "name": "Generali",
        "currency": "EUR",
        "country": "FR",
        "domain": "generali.fr",
    },
    "axa": {
        "name": "AXA",
        "currency": "EUR",
        "country": "FR",
        "domain": "axa.fr",
    },
    # ── Assurance vie — distributeurs / courtiers ─────────────────────────────
    "linxea": {
        "name": "Linxea",
        "currency": "EUR",
        "country": "FR",
        "domain": "linxea.com",
    },
    "meilleurtaux": {
        "name": "Meilleurtaux Placement",
        "currency": "EUR",
        "country": "FR",
        "domain": "meilleurtaux.com",
    },
}
