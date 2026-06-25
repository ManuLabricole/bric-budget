"""
tests/factories/transactions.py — Factory pour le modèle Transaction.

Montant en Decimal (SR-002). `import_hash` est unique (le modèle impose unique=True) :
on le dérive d'une Sequence → chaque transaction a un hash distinct sans collision,
comme le faisaient les helpers `make_tx` manuels des conftests.
"""

import hashlib
from decimal import Decimal

import factory
from django.utils import timezone

from transactions.models import Transaction

from .accounts import AccountFactory


class TransactionFactory(factory.django.DjangoModelFactory):
    """
    Mouvement minimal sur un compte. `currency` suit la devise du compte ;
    `amount` négatif par défaut (= débit, convention du modèle). `account` via
    SubFactory → un test peut passer son propre compte : TransactionFactory(account=acc).
    """

    class Meta:
        model = Transaction

    account = factory.SubFactory(AccountFactory)
    date = factory.LazyFunction(timezone.localdate)
    amount = Decimal("-25.40")
    currency = factory.SelfAttribute("account.currency")
    description_raw = factory.Sequence(lambda n: f"TEST TX {n}")
    import_hash = factory.Sequence(
        lambda n: hashlib.sha1(
            f"factory:{n}".encode(), usedforsecurity=False
        ).hexdigest()
    )
