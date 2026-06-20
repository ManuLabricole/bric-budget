"""
tests/accounts/test_colour_allocation.py — couleur stable des comptes (#134).

create_account() alloue à la création une colour_hex ∈ PALETTE, FIGÉE à vie, et
le domaine d'allocation est isolé PAR USER (SR-001). On teste le comportement
(couleur posée, distincte, stable, isolée), pas l'implémentation.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from accounts.models import Account, Institution
from accounts.services import create_account
from services.palette import PALETTE


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="colour-a@test.ch", password="pass"
    )


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(
        email="colour-b@test.ch", password="pass"
    )


@pytest.fixture
def institution(db):
    return Institution.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF"
    )


def _make(user, institution, name, contract):
    return create_account(
        user=user,
        institution=institution,
        account_type="savings",
        name=name,
        currency="CHF",
        contract_number=contract,
    )


@pytest.mark.django_db
def test_create_account_assigns_palette_colour(user, institution):
    """Un compte créé reçoit une colour_hex appartenant à la palette."""
    account = _make(user, institution, "Livret", "C-1")
    assert account.colour_hex
    assert account.colour_hex in PALETTE
    # Persisté, pas juste en mémoire.
    assert Account.objects.get(pk=account.pk).colour_hex == account.colour_hex


@pytest.mark.django_db
def test_two_accounts_same_user_get_distinct_colours(user, institution):
    """Deux comptes du même user ne partagent pas la couleur (< len(PALETTE))."""
    a = _make(user, institution, "A", "C-A")
    b = _make(user, institution, "B", "C-B")
    assert a.colour_hex != b.colour_hex
    assert a.colour_hex == PALETTE[0]
    assert b.colour_hex == PALETTE[1]


@pytest.mark.django_db
def test_colour_is_stable_when_more_accounts_arrive(user, institution):
    """La couleur d'un compte est FIGÉE : créer d'autres comptes ne la réassigne pas."""
    a = _make(user, institution, "A", "C-A")
    first_colour = a.colour_hex

    _make(user, institution, "B", "C-B")
    _make(user, institution, "C", "C-C")

    # Rechargé depuis la DB : inchangé.
    assert Account.objects.get(pk=a.pk).colour_hex == first_colour


@pytest.mark.django_db
def test_colour_domain_is_isolated_per_user(user, other_user, institution):
    """
    SR-001 : les couleurs du user A ne contraignent pas l'allocation du user B.

    Le 1er compte de CHAQUE user reçoit PALETTE[0] — preuve que le domaine
    d'allocation est bien filtré par for_user (pas global).
    """
    a = _make(user, institution, "A", "C-A")
    b = _make(other_user, institution, "B", "C-B")
    assert a.colour_hex == PALETTE[0]
    assert b.colour_hex == PALETTE[0]


@pytest.mark.django_db
def test_joint_account_colour_counts_for_both_members(user, other_user, institution):
    """
    Un compte joint réserve sa teinte dans le domaine des DEUX membres : le compte
    suivant de chaque membre prend la couleur d'après.
    """
    joint = _make(user, institution, "Joint", "C-J")
    joint.members.add(other_user)  # désormais joint

    # User A crée un 2e compte : doit éviter la couleur du joint.
    a2 = _make(user, institution, "A2", "C-A2")
    assert a2.colour_hex != joint.colour_hex

    # User B crée son 1er compte propre : il voit déjà le joint → couleur d'après.
    b1 = _make(other_user, institution, "B1", "C-B1")
    assert b1.colour_hex != joint.colour_hex
