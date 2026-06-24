"""
tests/factories/accounts.py — Factories pour l'app accounts.

Couvre Institution, Account (+ sous-modèles OneToOne Checking/Savings) et BalanceSnapshot.
Tous les montants sont des Decimal construits via `Decimal(str(...))` (SR-002) — jamais
`Decimal(float)`. Les identifiants bancaires (IBAN/contrat) sont GÉNÉRÉS, jamais codés en
dur depuis un vrai compte (SR-008).
"""

from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from accounts.models import (
    Account,
    BalanceSnapshot,
    CheckingAccount,
    Institution,
    SavingsAccount,
)


class InstitutionFactory(factory.django.DjangoModelFactory):
    """
    Institution financière fictive (banque par défaut, CHF/CH).

    django_get_or_create=("slug",) : le slug est unique ; réutiliser un slug déjà
    créé renvoie l'instance existante (plusieurs comptes peuvent partager une banque).
    Reproduit les fixtures `bank`/`chf_bank`/`chf_institution` (country=CH, CHF).
    """

    class Meta:
        model = Institution
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Test Bank {n}")
    slug = factory.Sequence(lambda n: f"test-bank-{n}")
    country = "CH"
    default_currency = "CHF"


class AccountFactory(factory.django.DjangoModelFactory):
    """
    Compte courant CHF générique, rattaché à une InstitutionFactory.

    `members` est un M2M → on le remplit en post_generation :
        AccountFactory(members=[user])  → user devient membre après le save.
    C'est la clé de l'isolation (Transaction.for_user filtre sur account__members).
    Sans `members=...`, le compte n'a aucun membre (comme certaines fixtures services/).
    """

    class Meta:
        model = Account
        skip_postgeneration_save = (
            True  # members.add() ne requiert pas de re-save de Account
        )

    institution = factory.SubFactory(InstitutionFactory)
    name = factory.Sequence(lambda n: f"Test Account {n}")
    account_type = "checking"
    currency = "CHF"

    @factory.post_generation
    def members(self, create, extracted, **kwargs):
        # extracted = la liste passée via AccountFactory(members=[...]).
        if not create or not extracted:
            return
        for user in extracted:
            self.members.add(user)


class CheckingAccountFactory(factory.django.DjangoModelFactory):
    """Détails compte courant (OneToOne Account). IBAN canonique = Account.iban."""

    class Meta:
        model = CheckingAccount

    account = factory.SubFactory(AccountFactory, account_type="checking")
    bic = ""


class SavingsAccountFactory(factory.django.DjangoModelFactory):
    """Détails compte épargne (OneToOne Account). Taux en Decimal (SR-002)."""

    class Meta:
        model = SavingsAccount

    account = factory.SubFactory(AccountFactory, account_type="savings", currency="CHF")
    interest_rate = Decimal("1.50")


class BalanceSnapshotFactory(factory.django.DjangoModelFactory):
    """
    Snapshot de solde à une date. `currency` suit la devise du compte ; `balance`
    en Decimal (SR-002). unique_together (account, date) → la date est séquencée
    pour éviter les collisions quand plusieurs snapshots ciblent le même compte.
    """

    class Meta:
        model = BalanceSnapshot

    account = factory.SubFactory(AccountFactory)
    date = factory.Sequence(lambda n: timezone.localdate() - timedelta(days=n))
    currency = factory.SelfAttribute("account.currency")
    balance = Decimal("1000.00")
