"""
tests/accounts/test_seed_accounts.py — commande `manage.py seed_accounts`.

Le test central est `test_seeded_account_is_visible_via_for_user` : l'ancienne
version de la commande créait l'Account sans jamais faire `members.add(user)`.
Le compte existait en base — donc un test qui aurait compté les Account serait
passé au vert — mais restait INVISIBLE partout dans l'app, puisque toute lecture
passe par `for_user()`, qui filtre sur `members` (SR-001). D'où l'assertion : on
interroge le compte comme l'app le fait, pas comme la base le stocke.

Les autres tests gardent ce que la délégation à `services.create_account()`
apporte et que la version manuelle avait perdu : sous-modèle du bon type,
Decimal exact sur le taux (SR-002), couleur de chart allouée, et l'atomicité
tout-ou-rien du seed (SR-003).
"""

import json
from decimal import Decimal
from typing import cast

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Account, CheckingAccount, SavingsAccount
from tests.factories import AccountFactory, InstitutionFactory, UserFactory

pytestmark = pytest.mark.django_db

IBAN_A = "CH0000000000000000000"
IBAN_B = "CH0000000000000000001"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user():
    return UserFactory(email="seed-target@budget.ch")


@pytest.fixture
def institutions():
    return {
        "ubs": InstitutionFactory(slug="ubs", name="UBS", default_currency="CHF"),
        "cic": InstitutionFactory(slug="cic", name="CIC", default_currency="EUR"),
    }


@pytest.fixture
def seed_file(tmp_path):
    """Fabrique un fichier de seed ; renvoie son chemin (str, pour call_command)."""

    def _write(*accounts, user_email="seed-target@budget.ch"):
        path = tmp_path / "accounts.json"
        path.write_text(
            json.dumps({"user_email": user_email, "accounts": list(accounts)}),
            encoding="utf-8",
        )
        return str(path)

    return _write


def checking(**overrides):
    return {
        "institution": "ubs",
        "name": "UBS Courant",
        "type": "checking",
        "currency": "CHF",
        "iban": IBAN_A,
        "bic": "AAAACHZZXXX",
        **overrides,
    }


def savings(**overrides):
    return {
        "institution": "ubs",
        "name": "UBS Épargne",
        "type": "savings",
        "currency": "CHF",
        "iban": IBAN_B,
        "interest_rate": "1.25",
        **overrides,
    }


# =============================================================================
# LA régression : le compte doit être RATTACHÉ, pas seulement créé
# =============================================================================


def test_seeded_account_is_visible_via_for_user(user, institutions, seed_file):
    """
    Le compte seedé doit être visible par le chemin que l'app emprunte.

    L'ancienne commande omettait members.add(user) : l'Account existait, mais
    `for_user()` ne le voyait pas — l'app affichait un patrimoine vide sans la
    moindre erreur. C'est exactement ce trou que ce test ferme.
    """
    call_command("seed_accounts", file=seed_file(checking()))

    visible = Account.objects.for_user(user)
    assert visible.count() == 1
    assert visible.first().name == "UBS Courant"


def test_seeded_account_is_not_visible_to_another_user(user, institutions, seed_file):
    """Corollaire SR-001 : le rattachement ne fuit pas vers un autre utilisateur."""
    other = UserFactory(email="autre@budget.ch")
    call_command("seed_accounts", file=seed_file(checking()))

    assert Account.objects.for_user(other).count() == 0


# =============================================================================
# Ce que la délégation aux services apporte
# =============================================================================


def test_checking_account_gets_its_details_and_bic(user, institutions, seed_file):
    call_command("seed_accounts", file=seed_file(checking()))

    account = Account.objects.for_user(user).get()
    assert account.iban == IBAN_A
    assert CheckingAccount.objects.get(account=account).bic == "AAAACHZZXXX"


def test_savings_account_rate_is_exact_decimal(user, institutions, seed_file):
    """SR-002 — un taux passé par float donnerait 1.2500000000000002."""
    call_command("seed_accounts", file=seed_file(savings()))

    account = Account.objects.for_user(user).get()
    assert SavingsAccount.objects.get(account=account).interest_rate == Decimal("1.25")


def test_account_gets_a_chart_colour(user, institutions, seed_file):
    """
    allocate_color() est appelé par create_account (#134). La commande manuelle
    d'avant ne le faisait pas → compte sans teinte stable dans les charts.
    """
    call_command("seed_accounts", file=seed_file(checking()))

    assert Account.objects.for_user(user).get().colour_hex != ""


def test_inactive_flag_is_applied(user, institutions, seed_file):
    """Un compte dormant reste en base mais sort de la résolution à l'import."""
    call_command("seed_accounts", file=seed_file(checking(is_active=False)))

    assert Account.objects.for_user(user).get().is_active is False


# =============================================================================
# Idempotence
# =============================================================================


def test_running_twice_does_not_duplicate(user, institutions, seed_file):
    path = seed_file(checking())
    call_command("seed_accounts", file=path)
    call_command("seed_accounts", file=path)

    assert Account.objects.for_user(user).count() == 1


def test_second_run_applies_renames(user, institutions, seed_file):
    """Corriger un nom dans le fichier et rejouer doit mettre à jour, pas dupliquer."""
    call_command("seed_accounts", file=seed_file(checking()))
    call_command("seed_accounts", file=seed_file(checking(name="UBS Compte principal")))

    account = Account.objects.for_user(user).get()
    assert account.name == "UBS Compte principal"


# =============================================================================
# Fail-closed : ne jamais toucher au compte d'un autre
# =============================================================================


def test_refuses_identity_owned_by_another_user(user, institutions, seed_file):
    """
    Un identifiant déjà porté par le compte de quelqu'un d'autre bloque le seed.

    Sans cette garde, le seed rattacherait à l'utilisateur courant un compte
    appartenant à un tiers — une fuite de données inter-utilisateurs (SR-001).
    """
    other = UserFactory(email="proprio@budget.ch")
    AccountFactory(
        institution=institutions["ubs"], iban=IBAN_A, members=[other], name="Déjà pris"
    )

    with pytest.raises(CommandError, match="proprio@budget.ch"):
        call_command("seed_accounts", file=seed_file(checking()))

    assert Account.objects.for_user(user).count() == 0


def test_adopts_an_orphan_account_instead_of_duplicating(user, institutions, seed_file):
    """
    Un compte sans aucun membre portant déjà l'identité est ADOPTÉ.

    En créer un second laisserait deux comptes au même identifiant : la
    résolution à l'import (`.filter(...).first()`) en choisirait un au hasard.
    """
    orphan = cast(
        Account,
        AccountFactory(institution=institutions["ubs"], iban=IBAN_A, name="Orphelin"),
    )

    call_command("seed_accounts", file=seed_file(checking()))

    assert Account.objects.for_user(user).count() == 1
    orphan.refresh_from_db()
    assert orphan.name == "UBS Courant"


# =============================================================================
# Tout-ou-rien (SR-003) et entrées incomplètes
# =============================================================================


def test_one_bad_account_writes_nothing(user, institutions, seed_file):
    """
    Le compte valide qui PRÉCÈDE l'entrée fautive ne doit pas être écrit.

    Un seed à moitié appliqué est pire qu'un seed refusé : on croit la base à
    jour alors qu'il manque des comptes, sans savoir lesquels.
    """
    path = seed_file(checking(), savings(institution="banque-inexistante"))

    with pytest.raises(CommandError, match="banque-inexistante"):
        call_command("seed_accounts", file=path)

    assert Account.objects.count() == 0


def test_account_without_identity_is_skipped_not_fatal(user, institutions, seed_file):
    """
    Le fichier se remplit banque après banque : une entrée encore vide est
    ignorée, elle ne doit pas empêcher de seeder les comptes déjà renseignés.
    """
    path = seed_file(checking(), checking(name="Pas prêt", iban="", bic=""))

    call_command("seed_accounts", file=path)

    assert [a.name for a in Account.objects.for_user(user)] == ["UBS Courant"]


def test_dry_run_writes_nothing(user, institutions, seed_file):
    call_command("seed_accounts", file=seed_file(checking()), dry_run=True)

    assert Account.objects.count() == 0


def test_unknown_user_is_rejected(institutions, seed_file):
    with pytest.raises(CommandError, match="introuvable"):
        call_command(
            "seed_accounts", file=seed_file(checking(), user_email="nobody@x.ch")
        )


def test_user_option_overrides_file(user, institutions, seed_file):
    """--user prime sur « user_email » — utile pour seeder un autre profil."""
    other = UserFactory(email="cible@budget.ch")
    call_command(
        "seed_accounts",
        file=seed_file(checking(), user_email=user.email),
        user=other.email,
    )

    assert Account.objects.for_user(other).count() == 1
    assert Account.objects.for_user(user).count() == 0
