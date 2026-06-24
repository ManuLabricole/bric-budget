"""
tests/demo/test_demo_account_scoping.py — #202

Avant #202, le seed démo résolvait les comptes par (institution, name) et reset_demo()
supprimait tous les comptes où le user démo était membre → en dev/staging partagé, un
compte RÉEL homonyme (ou partagé par erreur) pouvait être happé ou détruit. Le marqueur
déterministe is_demo isole strictement les comptes démo.
"""

import pytest
from django.contrib.auth import get_user_model

from accounts.models import Account, Institution
from demo.seeder import reset_demo


def _ubs():
    return Institution.objects.create(
        name="UBS", slug="ubs", country="CH", default_currency="CHF"
    )


@pytest.mark.django_db
def test_reset_demo_spares_real_account_even_if_demo_user_is_member(settings):
    settings.DEMO_USER_EMAIL = "demo@bric.ch"
    demo_user = get_user_model().objects.create_user(email="demo@bric.ch", password="x")
    inst = _ubs()
    real = Account.objects.create(
        institution=inst,
        name="UBS Compte courant",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_demo=False,
    )
    real.members.add(demo_user)  # même si le user démo est membre par erreur
    demo = Account.objects.create(
        institution=inst,
        name="UBS Compte courant (démo)",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_demo=True,
    )

    reset_demo()

    assert Account.objects.filter(id=real.id).exists()  # réel épargné
    assert not Account.objects.filter(id=demo.id).exists()  # démo supprimé


@pytest.mark.django_db
def test_seed_lookup_does_not_grab_real_homonym_account():
    inst = _ubs()
    real = Account.objects.create(
        institution=inst,
        name="UBS Compte courant",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_demo=False,
    )

    # Reproduit le get_or_create du seed (#202) : is_demo=True dans la clé.
    acc, created = Account.objects.get_or_create(
        institution=inst,
        name="UBS Compte courant",
        is_demo=True,
        defaults={
            "account_type": Account.AccountType.CHECKING,
            "currency": "CHF",
            "is_active": True,
        },
    )

    assert created is True  # un NOUVEAU compte démo, pas le réel
    assert acc.id != real.id
    assert acc.is_demo is True
