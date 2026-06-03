"""
transactions/management/commands/dev_seed_realistic.py

DEV ONLY — Seed 12 months of realistic transactions for a Geneva-based engineer.

Critères :
    - Revenus mensuels = dépenses × 1.30 (30% d'épargne nette)
    - Budget réaliste Genève : loyer 1 600, assurance maladie 380, etc.
    - Variance ±15% par transaction pour simuler le monde réel
    - Chaque catégorie a des marchands réalistes et une fréquence cohérente
    - Transactions réparties naturellement dans le mois (pas toutes le 1er)

Usage :
    python manage.py dev_seed_realistic
    python manage.py dev_seed_realistic --flush   # supprime les tx existantes d'abord
    make dev-seed-realistic

NE PAS exécuter en production.
"""

import hashlib
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from accounts.models import Account
from transactions.models import Category, Transaction

# ── Blueprint des dépenses mensuelles ─────────────────────────────────────────
#
# Chaque entrée : (category_slug, [liste de (merchant, montant_base, jour_préféré)])
# montant_base en CHF positif (on inverse au moment de créer la transaction).
# jour_préféré : jour du mois où la transaction a lieu (±3 jours de variance).
# Certains marchands ont plusieurs occurrences dans le mois (ex : Migros × 4).

EXPENSE_BLUEPRINT = [
    (
        "besoins-essentiels",
        [
            ("LOYER APPARTEMENT", 1_600, 1, True),  # loyer le 1er, récurrent
            ("CHARGES COPROPRIETE", 350, 1, True),
            ("ASSURANCE HABITATION", 150, 5, True),
            ("ELECTRICITE SIG", 100, 10, True),
        ],
    ),
    (
        "alimentation-boissons",
        [
            ("MIGROS", 130, 3, False),
            ("MIGROS", 120, 10, False),
            ("MIGROS", 110, 17, False),
            ("MIGROS", 115, 24, False),
            ("COOP", 90, 7, False),
            ("COOP", 85, 21, False),
            ("MANOR FOOD", 60, 14, False),
            ("RESTAURANT LE LYRIQUE", 55, 12, False),
            ("MCDONALDS GENEVE", 20, 22, False),
        ],
    ),
    (
        "factures-et-services",
        [
            ("SWISSCOM MOBILE", 80, 6, True),
            ("NETFLIX", 17, 8, True),
            ("SPOTIFY", 12, 8, True),
            ("AMAZON PRIME", 10, 8, True),
            ("ASSURANCE RC PRIVEE", 100, 10, True),
            ("SRG SSR REDEVANCE", 90, 15, True),  # redevance radio/TV
            ("GOOGLE WORKSPACE", 14, 8, True),
        ],
    ),
    (
        "auto-et-transports",
        [
            ("TPG ABONNEMENT MENSUEL", 70, 1, True),
            ("SBB CFF FFS", 120, 2, True),  # abonnement GA ou trajets
            ("ALVAREZ INVEST SARL", 59, 5, True),  # salle de sport
            ("STATION ESSO MEYRIN", 80, 8, False),
            ("PARKINGS GENEVE", 60, 15, False),
            ("UBER", 25, 20, False),
        ],
    ),
    (
        "sante",
        [
            ("ASSURANCE MALADIE CSS", 380, 1, True),
            ("PHARMACIE PRINCIPALE", 30, 14, False),
            ("CABINET DR BERNARD", 40, 0, False),  # occasionnel
        ],
    ),
    (
        "loisirs-et-divertissements",
        [
            ("CINEMA PATHÉ BALEXERT", 25, 9, False),
            ("STEAM GAMES", 20, 0, False),
            ("BAR LE VERRE A PIED", 45, 17, False),
            ("BOOKING.COM", 120, 0, False),  # occasionnel
            ("FNAC GENEVE", 30, 0, False),
        ],
    ),
    (
        "investissements",
        [
            ("FINPENSION 3A VIREMENT", 150, 26, True),
            ("FINPENSION LP VIREMENT", 300, 26, True),
        ],
    ),
    (
        "impots",
        [
            ("ACOMPTE IMPOTS ICC", 350, 15, True),
        ],
    ),
    (
        "frais",
        [
            ("UBS FRAIS DE COMPTE", 10, 28, True),
            ("FRAIS CHANGE EUR CHF", 20, 0, False),
            ("FRAIS DIVERS", 15, 0, False),
        ],
    ),
    (
        "remboursement-emprunt",
        [
            ("REMBOURSEMENT PRET PERSO", 180, 5, True),
        ],
    ),
    (
        "depenses-exceptionnelles",
        [
            ("IKEA AUBONNE", 120, 0, False),
            ("MANOR NON FOOD", 80, 0, False),
        ],
    ),
    (
        "depenses-professionnelles",
        [
            ("FNAC PRO MATERIEL", 60, 0, False),
            ("MIGROS INDUSTRIE", 30, 0, False),
        ],
    ),
    (
        "especes-et-cheques",
        [
            ("DISTRIBUTEUR UBS CAROUGE", 80, 5, False),
        ],
    ),
]

# ── Blueprint revenus mensuels ─────────────────────────────────────────────────
# Revenus = dépenses × 1.30 environ.
# Salaire ANTEIS SA : fixe le 25 du mois.
# Remboursements : aléatoires, 60% des mois seulement.

INCOME_BLUEPRINT = [
    (
        "revenus",
        [
            ("ANTEIS SA SALAIRE", 6_800, 25, True),  # salaire net mensuel
        ],
    ),
    (
        "remboursements",
        [
            ("ANTEIS SA NOTES FRAIS", 350, 28, False),  # 60% des mois
            ("REMBOURSEMENT ASSURANCE", 80, 0, False),  # occasionnel
        ],
    ),
]


def _jitter(amount: float, variance: float = 0.15) -> Decimal:
    """Applique une variance aléatoire ±variance% au montant."""
    factor = 1 + random.uniform(-variance, variance)
    return Decimal(str(round(amount * factor, 2)))


def _day_in_month(preferred_day: int, year: int, month: int) -> date:
    """
    Retourne une date dans le mois avec ±3 jours de variance par rapport au
    jour préféré. Clamp entre le 1er et le 28 pour éviter les jours invalides.
    """
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    if preferred_day == 0:
        # 0 = aléatoire dans le mois
        day = random.randint(1, last_day)
    else:
        day = preferred_day + random.randint(-3, 3)
        day = max(1, min(day, min(28, last_day)))
    return date(year, month, day)


def _make_hash(
    account_id: int, tx_date: date, amount: Decimal, desc: str, salt: int
) -> str:
    """
    Génère un import_hash unique (sha1 40 chars).
    Le salt est un compteur pour gérer les doublons même date+montant+marchant.
    """
    raw = f"dev_seed|{account_id}|{tx_date}|{amount}|{desc}|{salt}"
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()  # nosemgrep


class Command(BaseCommand):
    help = "DEV ONLY — Seed 12 months of realistic transactions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Supprime toutes les transactions existantes avant le seed",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=12,
            help="Nombre de mois à générer (défaut: 12)",
        )
        from transactions.management._dev_guard import add_force_prod_argument

        add_force_prod_argument(parser)

    def handle(self, *args, **options):
        from transactions.management._dev_guard import assert_dev_environment

        if not options.get("force_prod"):
            assert_dev_environment("dev_seed_realistic")

        self.stdout.write(
            self.style.WARNING(
                "\n⚠  DEV ONLY — seed réaliste de transactions.\n"
                "   Ne jamais exécuter en production.\n"
            )
        )

        # ── 1. Flush si demandé ───────────────────────────────────────────────
        if options["flush"]:
            count = Transaction.objects.count()
            Transaction.objects.all().delete()
            self.stdout.write(f"  🗑  {count} transactions supprimées.\n")

        # ── 2. Trouver le compte principal (Yuh C/C CHF) ──────────────────────
        # On préfère le compte Yuh, sinon le premier compte CHF actif disponible.
        account = (
            Account.objects.filter(institution__slug="yuh", is_active=True).first()
            or Account.objects.filter(currency="CHF", is_active=True).first()
        )
        if not account:
            self.stdout.write(
                self.style.ERROR(
                    "Aucun compte CHF actif trouvé. Lancez `make seed` d'abord."
                )
            )
            return

        self.stdout.write(f"  Compte cible : {account}\n")

        # ── 3. Charger les catégories par slug ────────────────────────────────
        cats = {c.slug: c for c in Category.objects.filter(is_active=True)}
        missing = []
        for slug, _ in EXPENSE_BLUEPRINT + INCOME_BLUEPRINT:
            if slug not in cats:
                missing.append(slug)
        if missing:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ Catégories introuvables : {missing}")
            )

        # ── 4. Générer les transactions ────────────────────────────────────────
        today = date.today()
        n_months = options["months"]
        to_create = []
        salt_counter = 0

        for month_offset in range(n_months - 1, -1, -1):
            # Mois cible (en remontant dans le temps)
            target = date(today.year, today.month, 1) - timedelta(
                days=30 * month_offset
            )
            year, month = target.year, target.month

            # ── Dépenses ──────────────────────────────────────────────────────
            for cat_slug, items in EXPENSE_BLUEPRINT:
                cat = cats.get(cat_slug)
                if not cat:
                    continue
                for merchant, base_amount, preferred_day, is_recurring in items:
                    # Transactions occasionnelles (preferred_day=0) : 60% de probabilité
                    if preferred_day == 0 and random.random() > 0.60:
                        continue

                    tx_date = _day_in_month(preferred_day, year, month)
                    amount = -_jitter(base_amount)  # négatif = dépense
                    salt_counter += 1

                    to_create.append(
                        Transaction(
                            account=account,
                            category=cat,
                            date=tx_date,
                            amount=amount,
                            amount_chf=amount,  # compte CHF → même montant
                            currency="CHF",
                            description_raw=merchant,
                            merchant_name=merchant,
                            is_recurring=is_recurring,
                            is_ignored=False,
                            is_internal_transfer=False,
                            categorization_source=Transaction.CategorizationSource.AI,
                            import_hash=_make_hash(
                                account.id, tx_date, amount, merchant, salt_counter
                            ),
                        )
                    )

            # ── Revenus ───────────────────────────────────────────────────────
            for cat_slug, items in INCOME_BLUEPRINT:
                cat = cats.get(cat_slug)
                if not cat:
                    continue
                for merchant, base_amount, preferred_day, is_recurring in items:
                    # Remboursements : présents 60% des mois seulement
                    if cat_slug == "remboursements" and random.random() > 0.60:
                        continue

                    tx_date = _day_in_month(preferred_day, year, month)
                    amount = _jitter(
                        base_amount, variance=0.05
                    )  # salaire = peu de variance
                    salt_counter += 1

                    to_create.append(
                        Transaction(
                            account=account,
                            category=cat,
                            date=tx_date,
                            amount=amount,
                            amount_chf=amount,
                            currency="CHF",
                            description_raw=merchant,
                            merchant_name=merchant,
                            is_recurring=is_recurring,
                            is_ignored=False,
                            is_internal_transfer=False,
                            categorization_source=Transaction.CategorizationSource.AI,
                            import_hash=_make_hash(
                                account.id, tx_date, amount, merchant, salt_counter
                            ),
                        )
                    )

        # ── 5. Bulk insert (ignore les doublons via import_hash) ──────────────
        # ignore_conflicts=True : si un import_hash existe déjà (ex: --flush pas utilisé),
        # la ligne est silencieusement ignorée → idempotent.
        created = Transaction.objects.bulk_create(to_create, ignore_conflicts=True)
        self.stdout.write(
            self.style.SUCCESS(
                f"\n  ✅ {len(created)} transactions créées sur {n_months} mois.\n"
                f"  Compte : {account}\n"
                f"  Reload /budget/ pour voir le résultat.\n"
            )
        )

        # ── 6. Rapport ratio revenus / dépenses ──────────────────────────────
        # Vérifie que le ratio 1.30 est respecté sur l'ensemble du seed.
        total_in = sum(t.amount for t in to_create if t.amount > 0)
        total_out = sum(abs(t.amount) for t in to_create if t.amount < 0)
        ratio = float(total_in / total_out) if total_out else 0

        self.stdout.write(
            f"  Revenus totaux  : +{total_in:,.0f} CHF\n"
            f"  Dépenses totales: -{total_out:,.0f} CHF\n"
            f"  Ratio revenus/dépenses : {ratio:.2f}x "
            f"({'✅' if 1.20 <= ratio <= 1.40 else '⚠ hors cible 1.30'})\n"
        )
