"""
demo/profiles.py — persona de démo (#118) : un·e ingénieur·e basé·e à Genève,
~6 800 CHF/mois, qui épargne. Adapté du blueprint de dev_seed_realistic.

On décrit des FLUX mensuels par compte, indépendamment du format de fichier.
generators.py les rend au format exact de chaque banque ; seeder.py les importe
via le vrai pipeline. Aucun identifiant réel : IBAN/cartes SYNTHÉTIQUES (SR-008).
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Identifiants synthétiques (0 donnée réelle — SR-008) ──────────────────────
# Mêmes que la fixture de test ubs_sample.csv (IBAN tout à zéro) → évidemment
# factices. Le seeder crée les comptes avec ces identifiants ; les générateurs
# les écrivent dans les fichiers → le resolver d'import les matche.
DEMO_UBS_CHECKING_IBAN = "CH00 0000 0000 0000 0000 0"
DEMO_UBS_SAVINGS_IBAN = "CH00 0000 0000 0000 0000 1"
DEMO_UBS_CHECKING_NUMBER = "0000 00000000.00"
DEMO_UBS_SAVINGS_NUMBER = "0000 00000000.01"
DEMO_YUH_CARD_LAST_FOUR = "1150"


@dataclass(frozen=True)
class Flow:
    """Un flux récurrent ou occasionnel sur un compte.

    amount    : magnitude en CHF, toujours positive (le signe vient de direction).
    day       : jour préféré du mois (0 = aléatoire), ±3 jours de variance appliqués.
    direction : "debit" (sortie) ou "credit" (entrée).
    recurrent : True = chaque mois ; False ≈ 60% des mois (occasionnel).
    """

    label: str
    amount: float
    day: int
    direction: str
    recurrent: bool = True


# Compte courant UBS : salaire entrant, charges fixes, virement épargne sortant.
UBS_CHECKING_FLOWS: list[Flow] = [
    Flow("ANTEIS SA SALAIRE", 6800, 25, "credit"),
    Flow("LOYER APPARTEMENT GENEVE", 1600, 1, "debit"),
    Flow("ASSURANCE MALADIE CSS", 380, 1, "debit"),
    Flow("CHARGES COPROPRIETE", 350, 1, "debit"),
    Flow("SWISSCOM MOBILE", 80, 6, "debit"),
    Flow("ELECTRICITE SIG", 100, 10, "debit"),
    Flow("ACOMPTE IMPOTS ICC", 350, 15, "debit"),
    Flow("VIREMENT COMPTE EPARGNE", 1000, 26, "debit"),
    Flow("NOTES DE FRAIS ANTEIS SA", 350, 28, "credit", recurrent=False),
]

# Livret UBS : reçoit le virement d'épargne mensuel (miroir du courant).
UBS_SAVINGS_FLOWS: list[Flow] = [
    Flow("VIREMENT DEPUIS COMPTE COURANT", 1000, 26, "credit"),
]

# Carte Yuh : dépenses du quotidien (toutes des CARD_TRANSACTION_OUT).
YUH_CARD_FLOWS: list[Flow] = [
    Flow("MIGROS GENEVE", 95, 3, "debit"),
    Flow("MIGROS GENEVE", 110, 11, "debit"),
    Flow("COOP PFISTER", 80, 7, "debit"),
    Flow("COOP PFISTER", 70, 21, "debit"),
    Flow("MANOR FOOD", 55, 14, "debit"),
    Flow("TPG ABONNEMENT", 70, 2, "debit"),
    Flow("CFF MOBILE", 45, 9, "debit", recurrent=False),
    Flow("RESTAURANT LE LYRIQUE", 60, 13, "debit", recurrent=False),
    Flow("PHARMACIE PRINCIPALE", 35, 17, "debit", recurrent=False),
    Flow("NETFLIX", 20, 8, "debit"),
    Flow("STARBUCKS GENEVE", 12, 0, "debit", recurrent=False),
]

# Épargne Yuh : versement mensuel entrant (transfert vers l'épargne).
YUH_SAVINGS_FLOWS: list[Flow] = [
    Flow("VERSEMENT EPARGNE YUH", 250, 27, "credit"),
]


# ── Règles de catégorisation démo ─────────────────────────────────────────────
# (keyword cherché dans description_raw, slug catégorie, slug sous-catégorie|None,
# priorité). Slugs RÉELS du référentiel (underscore). Les "VIREMENT…" pointent sur
# `virements` → déclenche le flag virement interne (is_internal_transfer/is_ignored).
DEMO_RULES = [
    ("SALAIRE", "revenus", "salaire", 100),
    ("VIREMENT COMPTE EPARGNE", "virements", "transferts_internes", 95),
    ("VIREMENT DEPUIS COMPTE COURANT", "virements", "transferts_internes", 95),
    ("NOTES DE FRAIS", "remboursements", None, 90),
    ("LOYER", "besoins_essentiels", "loyer", 80),
    ("CHARGES COPROPRIETE", "besoins_essentiels", "frais_loyer", 80),
    ("ASSURANCE MALADIE", "sante", "assurance_maladie", 80),
    ("SWISSCOM", "factures_services", "telephone_portable", 70),
    ("ELECTRICITE", "factures_services", "electricite", 70),
    ("ACOMPTE IMPOTS", "impots", "impots_generaux", 70),
    ("MIGROS", "alimentation_boissons", "courses", 60),
    ("COOP", "alimentation_boissons", "courses", 60),
    ("MANOR FOOD", "alimentation_boissons", "courses", 60),
    ("RESTAURANT", "alimentation_boissons", "restaurants", 60),
    ("STARBUCKS", "alimentation_boissons", "cafes", 60),
    ("TPG", "auto_transports", "transports_publics", 60),
    ("CFF", "auto_transports", "transports_publics", 60),
    ("PHARMACIE", "sante", "medicaments", 60),
    ("NETFLIX", "loisirs_divertissements", "abonnements_loisirs", 60),
    # CIC (EUR) + épargne Yuh
    ("VERSEMENT EPARGNE", "virements", "transferts_internes", 95),
    ("MONOPRIX", "alimentation_boissons", "courses", 60),
    ("SNCF", "auto_transports", "billets_train", 60),
]
