"""
transactions/management/commands/_seed_perso_data.py — données du seed PERSO (#146).

Données committées et CURÉES du seed perso de l'admin (commande `seed_perso`) :
les catégories perso + les règles de catégorisation exportées de Finary du
propriétaire (Emmanuel), seedées `owner=<user>`, `is_system=False`.

⛔ SR-008 — AUCUN identifiant bancaire réel ici (ni IBAN, ni RIB, ni n° de contrat).
Les règles sont des MOTS-CLÉS MARCHANDS génériques (« MIGROS », « NETFLIX »…) cherchés
dans la description de transaction — jamais un numéro de compte. C'est ce qui rend ce
fichier committable sans risque (≠ les comptes perso, qui passent par .env / setup_accounts).

Pourquoi inline (Python) et PAS dans `transactions/reference/*.json` :
    `reference/` est réservé au référentiel SYSTÈME PARTAGÉ (owner NULL), gardé par
    `tests/test_reference_data.py` (SR-008) et seedé par `sync_reference_data` à chaque
    deploy. Ces données-ci sont PERSO (owner=user) → on suit le précédent de
    `demo/profiles.py` (data de seed inline, typée).
"""

from __future__ import annotations

# PersoCat = (name, slug, icon, parent_slug, colour_hex). On réutilise la dataclass
# déjà définie pour le seed démo plutôt que d'en dupliquer une (même shape, même
# contrat parent système|perso résolu par `budget.utils.seed_perso_categories`).
from demo.profiles import PersoCat

# ── Catégories perso ─────────────────────────────────────────────────────────
# parent_slug=None    → catégorie perso top-level (colour_hex utilisé)
# parent_slug="<slug>"→ sous-cat rattachée à ce parent (catégorie SYSTÈME partagée
#                        OU une perso top-level ci-dessous ; résolution par slug avec
#                        préférence perso, cf. seed_perso_categories).
PERSO_CATEGORIES: list[PersoCat] = [
    # Catégorie perso top-level + ses sous-catégories.
    PersoCat(
        "Dépenses exceptionnelles",
        "depenses_exceptionnelles",
        "rosette",
        colour_hex="#204cff",
    ),
    PersoCat("Déménagement", "demenagement", "truck", "depenses_exceptionnelles"),
    PersoCat("Mariage", "mariage", "heart", "depenses_exceptionnelles"),
    PersoCat(
        "Voyages",
        "voyages",
        "plane",
        colour_hex="#0ea5e9",
    ),
    PersoCat("Vols", "vols", "plane-departure", "voyages"),
    PersoCat("Hôtels", "hotels", "bed", "voyages"),
    PersoCat("Location voiture", "location_voiture", "car", "voyages"),
    # Sous-catégories perso rattachées à des catégories SYSTÈME (partagées) — exactement
    # le cas qui fuyait avant le fix SR-013 (une perso sous une cat système).
    PersoCat("Concert", "concert", "music", "loisirs_divertissements"),
    PersoCat("Livres", "livres", "book", "loisirs_divertissements"),
    PersoCat("Vélo", "velo", "bike", "loisirs_divertissements"),
    PersoCat("Streaming", "streaming", "device-tv", "loisirs_divertissements"),
    PersoCat("Uber Eats", "uber_eats", "moped", "alimentation_boissons"),
    PersoCat("Repas maison", "repas_maison", "chef-hat", "alimentation_boissons"),
    PersoCat("Amendes", "amendes", "file-invoice", "auto_transports"),
    PersoCat(
        "Aménagement / Bricolage",
        "amenagement_bricolage",
        "hammer",
        "besoins_essentiels",
    ),
]


# ── Règles de catégorisation exportées de Finary ─────────────────────────────
# (keyword cherché dans le champ cible, slug catégorie, slug sous-catégorie|None, priorité).
# Slugs RÉELS du référentiel système committé (underscore) OU des catégories perso ci-dessus
# (ex. `streaming`, `velo`, `voyages`) — résolus `for_user(user)` (système OU perso de CE user).
# Les « VIREMENT… » pointent sur `virements` → flag virement interne à l'apply.
# SR-008 : que des marques/mots-clés génériques, zéro identifiant bancaire.
#
# Type : (keyword, category_slug, subcategory_slug | None, priority).
FINARY_RULES: list[tuple[str, str, str | None, int]] = [
    # Revenus & virements (priorité haute : on les fixe avant tout le reste).
    ("SALAIRE", "revenus", "salaire", 100),
    ("VIREMENT EPARGNE", "virements", "transferts_internes", 95),
    ("VIREMENT COMPTE EPARGNE", "virements", "transferts_internes", 95),
    ("VERSEMENT EPARGNE", "virements", "transferts_internes", 95),
    ("NOTES DE FRAIS", "remboursements", None, 90),
    # Charges fixes / besoins essentiels.
    ("LOYER", "besoins_essentiels", "loyer", 80),
    ("CHARGES COPROPRIETE", "besoins_essentiels", "frais_loyer", 80),
    ("ASSURANCE MALADIE", "sante", "assurance_maladie", 80),
    ("SWISSCOM", "factures_services", "telephone_portable", 70),
    ("SALT", "factures_services", "telephone_portable", 70),
    ("ELECTRICITE", "factures_services", "electricite", 70),
    ("ACOMPTE IMPOTS", "impots", "impots_generaux", 70),
    # Alimentation.
    ("MIGROS", "alimentation_boissons", "courses", 60),
    ("COOP", "alimentation_boissons", "courses", 60),
    ("MANOR FOOD", "alimentation_boissons", "courses", 60),
    ("MONOPRIX", "alimentation_boissons", "courses", 60),
    ("ALDI", "alimentation_boissons", "courses", 60),
    ("LIDL", "alimentation_boissons", "courses", 60),
    ("RESTAURANT", "alimentation_boissons", "restaurants", 60),
    ("STARBUCKS", "alimentation_boissons", "cafes", 60),
    # Uber Eats → sous-cat PERSO `uber_eats` sous la cat SYSTÈME `alimentation_boissons`.
    ("UBER EATS", "alimentation_boissons", "uber_eats", 65),
    # Transports.
    ("TPG", "auto_transports", "transports_publics", 60),
    ("CFF", "auto_transports", "transports_publics", 60),
    ("SNCF", "auto_transports", "billets_train", 60),
    # Amendes → sous-cat PERSO `amendes` sous la cat SYSTÈME `auto_transports`.
    ("AMENDE", "auto_transports", "amendes", 65),
    # Loisirs / abonnements → sous-cats PERSO sous la cat SYSTÈME `loisirs_divertissements`.
    ("NETFLIX", "loisirs_divertissements", "streaming", 65),
    ("SPOTIFY", "loisirs_divertissements", "streaming", 65),
    ("DISNEY", "loisirs_divertissements", "streaming", 65),
    ("FNAC", "loisirs_divertissements", "livres", 65),
    ("DECATHLON", "loisirs_divertissements", "velo", 55),
    # Voyages → cat PERSO top-level `voyages` + ses sous-cats PERSO.
    ("BOOKING.COM", "voyages", "hotels", 65),
    ("AIRBNB", "voyages", "hotels", 65),
    ("EASYJET", "voyages", "vols", 65),
    ("SWISS AIR", "voyages", "vols", 65),
    ("HERTZ", "voyages", "location_voiture", 65),
    # Bricolage / aménagement → sous-cat PERSO sous la cat SYSTÈME `besoins_essentiels`.
    ("IKEA", "besoins_essentiels", "amenagement_bricolage", 55),
    ("BRICO", "besoins_essentiels", "amenagement_bricolage", 55),
]
