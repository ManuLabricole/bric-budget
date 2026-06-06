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

# Institutions de référence : (name, slug fallback, icon_slug, country, currency, domain).
# _seed_institutions cherche d'abord une institution RÉELLE avec le même icon_slug
# pour éviter les doublons ("Yuh" et "Yuh (démo)"). Si aucune n'existe, elle crée
# avec le slug fallback.
INSTITUTIONS = [
    ("Yuh", "demo-yuh", "yuh", "CH", "CHF", "yuh.ch"),
    ("CIC", "demo-cic", "cic", "FR", "EUR", "cic.fr"),
    ("BoursoBank", "demo-boursobank", "boursorama", "FR", "EUR", "boursobank.com"),
]

# Comptes démo : (institution_slug, name, account_type, currency, valeur_départ, drift_mensuel).
# drift = variation structurelle mensuelle hors bruit aléatoire.
# Conçu pour avoir des croisements de courbes sur 12 mois :
#   Yuh Courant (CHF, -4%/mois) croise CIC Courant (EUR, +5%/mois) vers le mois 4-5.
#   CIC a 2 comptes courants → le groupement par institution est visible dans la liste.
ACCOUNTS = [
    ("demo-yuh", "Yuh Courant", "checking", "CHF", Decimal("5400"), Decimal("-0.04")),
    ("demo-yuh", "Yuh Save CHF", "savings", "CHF", Decimal("8200"), Decimal("0.006")),
    ("demo-cic", "CIC Courant", "checking", "EUR", Decimal("2300"), Decimal("0.05")),
    ("demo-cic", "CIC Pro", "checking", "EUR", Decimal("890"), Decimal("0.015")),
    ("demo-cic", "CIC Livret A", "savings", "EUR", Decimal("17000"), Decimal("0.003")),
    ("demo-cic", "CIC LDDS", "savings", "EUR", Decimal("1200"), Decimal("0.002")),
    (
        "demo-boursobank",
        "BoursoBank Courant",
        "checking",
        "EUR",
        Decimal("1450"),
        Decimal("-0.008"),
    ),
    (
        "demo-boursobank",
        "Bourso Épargne",
        "savings",
        "EUR",
        Decimal("4300"),
        Decimal("0.004"),
    ),
]


# Noms exacts des comptes créés par ce seed — utilisés par _wipe_demo_accounts
# pour identifier les comptes démo sans dépendre du slug d'institution.
_DEMO_ACCOUNT_NAMES = frozenset(name for _, name, *_ in ACCOUNTS)


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
        for inst_slug, name, atype, currency, base, drift in ACCOUNTS:
            acc = Account.objects.create(
                institution=institutions[inst_slug],
                name=name,
                account_type=atype,
                currency=currency,
            )
            acc.members.add(user)
            n_acc += 1
            s, t = self._seed_history(acc, base, drift, today)
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
        """Réutilise les institutions réelles (même icon_slug) ; crée si absentes.

        Évite les doublons visuels ("Yuh" + "Yuh (démo)") en cherchant d'abord
        une institution existante avec le même icon_slug.
        """
        result = {}
        for name, slug, icon_slug, country, currency, domain in INSTITUTIONS:
            inst = (
                Institution.objects.filter(icon_slug=icon_slug).order_by("id").first()
            )
            if inst is None:
                inst, _ = Institution.objects.get_or_create(
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
        """Efface les comptes démo identifiés par leur nom exact (_DEMO_ACCOUNT_NAMES).

        On ne filtre plus par institution__slug (les comptes démo sont désormais
        attachés aux institutions réelles pour éviter les doublons visuels).
        """
        accs = Account.objects.filter(name__in=_DEMO_ACCOUNT_NAMES, members=user)
        Transaction.objects.filter(account__in=accs).delete()
        BalanceSnapshot.objects.filter(account__in=accs).delete()
        accs.delete()

    def _seed_history(
        self, acc: Account, base: Decimal, drift: Decimal, today: datetime.date
    ):
        """Snapshots mensuels (12 mois) + transactions entre les ancres.

        drift = variation structurelle mensuelle (ex. -0.04 → −4%/mois).
        Le bruit aléatoire est volontairement faible pour que les drifts différenciés
        produisent des croisements de courbes visibles sur le graphe.
        """
        n_snap, n_tx = 0, 0
        value = base
        counter = 0
        is_savings = acc.account_type == "savings"
        growth = Decimal("1") + drift

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
                        import_hash=hashlib.sha256(
                            f"demo:{acc.id}:{tx_date}:{counter}".encode(),
                        ).hexdigest(),
                    )
                    n_tx += 1
                # Bruit réduit (±1.5%) pour que le drift structurel soit lisible.
                noise = Decimal(str(round(random.uniform(-0.015, 0.015), 4)))
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
