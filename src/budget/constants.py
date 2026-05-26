"""
budget/constants.py — Constantes métier de l'app Budget.

Séparées de views.py pour éviter les imports circulaires et faciliter
la réutilisation dans les tests et les futures vues fragmentées.
"""

# Nombre de mois dans chaque mode de période.
PERIOD_MODE_MONTHS = {"1m": 1, "3m": 3, "1y": 12}

# Tokens banque sans valeur sémantique pour les règles de catégorisation.
# Filtrés lors de la génération des chips — ne doivent pas apparaître comme suggestions.
# Source : métadonnées Yuh (CHF) et CIC (EUR), codes de paiement standard CH/EU.
RULE_NOISE_TOKENS = {
    # Types de paiement et terminaux
    "PSC",
    "CB",
    "TPE",
    "NFC",
    "SCV",
    "SCC",
    # Verbes / mots d'action banque
    "PAIEMENT",
    "RETRAIT",
    "ACHAT",
    "VIREMENT",
    "VIR",
    "PRELEVEMENT",
    "SEPA",
    "DEBIT",
    "CREDIT",
    "ORDRE",
    "TRANSFERT",
    "REMISE",
    "DEPOT",
    # Instruments de paiement
    "CARTE",
    "CARD",
    "VISA",
    "MASTERCARD",
    "MAESTRO",
    "TWINT",
    "PAYPAL",
    # Devises
    "CHF",
    "EUR",
    "GBP",
    "USD",
    "CAD",
    "JPY",
    # Codes pays / zones
    "CH",
    "FR",
    "DE",
    "BE",
    "LU",
    "UK",
    "EU",
    # Mots génériques bruit
    "SANS",
    "CONTACT",
    "BANCAIRE",
    "BANQUE",
    "TRANSACTION",
    "PRET",
    "NO",
    "NUM",
    "REF",
    "ID",
    "PAY",
    "PAYMENT",
    "NUMERO",
    "CODE",
}

# 16 pastels harmonieux sur fond très sombre (#131314).
# Les 5 premières sont les couleurs déjà utilisées par les catégories système.
# Donnée métier (pas un token UI) — stockée ici, pas dans Tailwind.
CATEGORY_COLOR_PALETTE = [
    {"hex": "#eed8b4", "name": "Ocre"},
    {"hex": "#deab5e", "name": "Caramel"},
    {"hex": "#e77f79", "name": "Corail"},
    {"hex": "#5abdc5", "name": "Cyan"},
    {"hex": "#63e096", "name": "Menthe"},
    {"hex": "#b09be8", "name": "Lavande"},
    {"hex": "#f09e5a", "name": "Orange"},
    {"hex": "#7ec8e3", "name": "Ciel"},
    {"hex": "#f0c878", "name": "Miel"},
    {"hex": "#e8a0b0", "name": "Rose"},
    {"hex": "#95d4b4", "name": "Sauge"},
    {"hex": "#d4a0d0", "name": "Lilas"},
    {"hex": "#c8d87c", "name": "Citron"},
    {"hex": "#a0c8f8", "name": "Bleu"},
    {"hex": "#98d8d8", "name": "Turquoise"},
    {"hex": "#e8c8a8", "name": "Sable"},
]

# 40 icônes disponibles dans le picker de création de catégorie.
# Ordonnées par thème pour un affichage cohérent en grille 8 colonnes.
CURATED_ICONS = [
    # Alimentation (4)
    "burger",
    "coffee",
    "chef-hat",
    "tools-kitchen",
    # Transports (6)
    "car",
    "bus",
    "train",
    "plane",
    "bike",
    "parking",
    # Shopping & style (3)
    "basket",
    "shirt",
    "tag",
    # Santé (3)
    "pill",
    "stethoscope",
    "first-aid-kit",
    # Logement (5)
    "home",
    "key",
    "bolt",
    "flame",
    "tool",
    # Finance & travail (7)
    "wallet",
    "coin",
    "pig-money",
    "briefcase",
    "file-invoice",
    "receipt",
    "percentage",
    # Loisirs & culture (7)
    "movie",
    "music",
    "ball-football",
    "beach",
    "luggage",
    "gift",
    "book",
    # Famille, animaux & divers (5)
    "device-laptop",
    "wifi",
    "users",
    "baby-carriage",
    "paw",
]

# Noms des mois en français (index = numéro de mois).
MOIS_FR = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}
