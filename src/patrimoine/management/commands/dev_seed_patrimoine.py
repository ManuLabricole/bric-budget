"""
patrimoine/management/commands/seed_patrimoine_demo.py — DEV ONLY.

Peuple un dashboard patrimoine réaliste pour VOIR le bilan fonctionner :
institutions (avec logos), comptes courants + livrets, snapshots mensuels (les
valeurs/ancres) sur ~12 mois, et transactions entre les ancres (les « imports »).

⚠️ ISOLATION TOTALE — ne touche JAMAIS aux vraies données :
  - utilisateur DÉMO dédié (demo@bricbudget.local),
  - institutions DÉMO dédiées (slug `demo-*`, mais icon_slug réel pour les logos).
Idempotent : efface puis recrée les comptes démo de l'utilisateur démo.

    python src/manage.py seed_patrimoine_demo
    python src/manage.py seed_patrimoine_demo --email moi@test.ch   # cible un autre user
"""

from __future__ import annotations

import calendar
import datetime
import hashlib
import random
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Account, BalanceSnapshot, Institution
from transactions.models import Transaction

DEMO_EMAIL = "demo@bricbudget.local"
DEMO_PASSWORD = "demo1234"  # noqa: S105 — compte démo DEV uniquement, jamais en prod

EUR_TO_CHF = Decimal("0.95")  # taux démo fixe

# Institutions DÉMO : (name, slug DÉMO isolé, icon_slug RÉEL, country, currency, domain).
# slug `demo-*` → n'entre jamais en collision avec les vraies institutions.
# icon_slug réel (yuh/cic/boursobank) → les logos existants se résolvent.
INSTITUTIONS = [
    ("Yuh (démo)", "demo-yuh", "yuh", "CH", "CHF", "yuh.ch"),
    ("CIC (démo)", "demo-cic", "cic", "FR", "EUR", "cic.fr"),
    (
        "BoursoBank (démo)",
        "demo-boursobank",
        "boursorama",  # fichier logo = boursorama.png
        "FR",
        "EUR",
        "boursobank.com",
    ),
]

# Comptes démo : (institution_slug, name, account_type, currency, valeur de départ).
# Variété volontaire (plusieurs institutions × checking/savings) pour un donut parlant.
ACCOUNTS = [
    ("demo-yuh", "Yuh Courant", "checking", "CHF", Decimal("5400")),
    ("demo-yuh", "Yuh Save CHF", "savings", "CHF", Decimal("8200")),
    ("demo-cic", "CIC Compte Courant", "checking", "EUR", Decimal("2300")),
    ("demo-cic", "CIC Livret A", "savings", "EUR", Decimal("17000")),
    ("demo-cic", "CIC LDDS", "savings", "EUR", Decimal("1200")),
    ("demo-boursobank", "BoursoBank Courant", "checking", "EUR", Decimal("1450")),
    ("demo-boursobank", "Bourso Épargne", "savings", "EUR", Decimal("4300")),
]


def _to_chf(amount: Decimal, currency: str) -> Decimal:
    return (
        amount if currency == "CHF" else (amount * EUR_TO_CHF).quantize(Decimal("0.01"))
    )


def _first_of_month_ago(today: datetime.date, months: int) -> datetime.date:
    m = today.month - months
    year = today.year + (m - 1) // 12
    month = (m - 1) % 12 + 1
    return datetime.date(year, month, 1)


class Command(BaseCommand):
    help = "DEV ONLY — Seed patrimoine démo isolé (user + institutions démo dédiés)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            help="Cible un user existant au lieu du user démo dédié.",
        )
        parser.add_argument("--seed", type=int, default=42, help="Graine aléatoire.")

    @transaction.atomic
    def handle(self, *args, **options):
        # Garde-fou : commande DEV uniquement, jamais en prod (DEBUG=False).
        if not settings.DEBUG:
            raise CommandError("Commande DEV uniquement — refusée avec DEBUG=False.")
        random.seed(options["seed"])
        user, created_user = self._get_user(options.get("email"))
        today = timezone.localdate()

        institutions = self._seed_institutions()
        self._wipe_demo_accounts(user)

        n_acc, n_snap, n_tx = 0, 0, 0
        for inst_slug, name, atype, currency, base in ACCOUNTS:
            acc = Account.objects.create(
                institution=institutions[inst_slug],
                name=name,
                account_type=atype,
                currency=currency,
            )
            acc.members.add(user)
            n_acc += 1
            s, t = self._seed_history(acc, base, today)
            n_snap += s
            n_tx += t

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Démo patrimoine : {n_acc} comptes, {n_snap} snapshots, {n_tx} transactions."
            )
        )
        if created_user:
            self.stdout.write(
                self.style.WARNING(
                    f"👤 Connexion démo → email: {DEMO_EMAIL}  mot de passe: {DEMO_PASSWORD}"
                )
            )
        else:
            self.stdout.write(f"👤 Données ajoutées à : {user.email}")

    # -- helpers ---------------------------------------------------------------

    def _get_user(self, email: str | None):
        """User démo dédié par défaut ; sinon le user --email (jamais wipe au-delà du démo)."""
        User = get_user_model()
        if email:
            user = User.objects.filter(email=email).first()
            if user is None:
                raise CommandError(f"Aucun utilisateur avec l'email {email}.")
            return user, False
        user = User.objects.filter(email=DEMO_EMAIL).first()
        if user is not None:
            return user, False
        user = User.objects.create_user(email=DEMO_EMAIL, password=DEMO_PASSWORD)
        return user, True

    def _seed_institutions(self) -> dict[str, Institution]:
        result = {}
        for name, slug, icon_slug, country, currency, domain in INSTITUTIONS:
            inst, _ = Institution.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "country": country,
                    "default_currency": currency,
                    "icon_slug": icon_slug,
                    "domain": domain,
                },
            )
            result[slug] = inst
        return result

    def _wipe_demo_accounts(self, user) -> None:
        """Efface UNIQUEMENT les comptes démo (institutions `demo-*`) de l'utilisateur."""
        accs = Account.objects.filter(
            institution__slug__startswith="demo-", members=user
        )
        Transaction.objects.filter(account__in=accs).delete()
        BalanceSnapshot.objects.filter(account__in=accs).delete()
        accs.delete()

    def _seed_history(self, acc: Account, base: Decimal, today: datetime.date):
        """Snapshots mensuels (12 mois) + transactions entre les ancres."""
        n_snap, n_tx = 0, 0
        value = base
        counter = 0
        is_savings = acc.account_type == "savings"

        for months_ago in range(12, -1, -1):
            snap_date = _first_of_month_ago(today, months_ago)
            BalanceSnapshot.objects.create(
                account=acc,
                date=snap_date,
                balance=value,
                computed_balance=value,
                currency=acc.currency,
                balance_chf=_to_chf(value, acc.currency),
            )
            n_snap += 1

            if months_ago > 0:
                for tx_date, amount in self._month_transactions(
                    acc, snap_date, is_savings
                ):
                    counter += 1
                    Transaction.objects.create(
                        account=acc,
                        date=tx_date,
                        amount=amount,
                        currency=acc.currency,
                        amount_chf=_to_chf(amount, acc.currency),
                        description_raw=self._label(amount, is_savings),
                        import_hash=hashlib.sha1(
                            f"demo:{acc.id}:{tx_date}:{counter}".encode(),
                            usedforsecurity=False,
                        ).hexdigest(),
                    )
                    n_tx += 1
                growth = Decimal("1.004") if is_savings else Decimal("1.0")
                noise = Decimal(str(round(random.uniform(-0.04, 0.06), 4)))
                value = (value * growth * (1 + noise)).quantize(Decimal("0.01"))
                value = max(value, Decimal("1"))

        return n_snap, n_tx

    def _month_transactions(self, acc, snap_date, is_savings):
        last_day = calendar.monthrange(snap_date.year, snap_date.month)[1]

        def d(day):
            return snap_date.replace(day=min(day, last_day))

        if is_savings:
            return [(d(5), Decimal(str(round(random.uniform(50, 300), 2))))]
        return [
            (d(2), Decimal(str(round(random.uniform(3000, 4200), 2)))),  # salaire
            (d(8), Decimal(str(-round(random.uniform(800, 1400), 2)))),  # loyer
            (d(15), Decimal(str(-round(random.uniform(100, 400), 2)))),
            (d(22), Decimal(str(-round(random.uniform(50, 250), 2)))),
        ]

    def _label(self, amount: Decimal, is_savings: bool) -> str:
        if is_savings:
            return "Versement épargne"
        if amount > 0:
            return "Salaire"
        return random.choice(
            ["Loyer", "Courses Coop", "Restaurant", "Transports", "Abonnement"]
        )
