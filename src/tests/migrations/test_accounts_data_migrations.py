"""
Tests des data-migrations RunPython de l'app `accounts` (issue #197).

Pourquoi tester des migrations déjà « exécutées » ?
    `manage.py migrate` exécute le RunPython, donc sa couverture de ligne est verte,
    mais sa LOGIQUE de transformation (état avant → état après) n'est jamais vérifiée.
    On utilise `django-test-migrations` (fixture `migrator`) qui rejoue chaque migration
    sur l'état HISTORIQUE des modèles — indispensable ici car plusieurs champs/relations
    ont changé depuis (ex. `Account.bank` renommé en `Account.institution` par
    accounts/0015, donc 0014 voit encore `bank`).

Pour chaque RunPython on prouve :
    1. l'état APRÈS (le backfill fait ce qu'il prétend),
    2. l'idempotence (rejouer la migration ne change rien),
    3. la réversibilité (le reverse_code ramène à l'état pré-migration) — SR-004.

Les modèles sont récupérés via `state.apps.get_model(...)` (versions figées), jamais
importés directement : c'est la règle Django pour rester indépendant du code courant.
"""

from __future__ import annotations

import pytest
from django.db.migrations.state import ProjectState

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Helpers — créent des données via les MODÈLES FIGÉS passés en argument.       #
# On ne réutilise pas les factories partagées (#194) : la fixture migrator est #
# autonome et doit manipuler l'état historique, pas les modèles courants.      #
# --------------------------------------------------------------------------- #
def _make_bank(state: ProjectState, *, slug: str, name: str | None = None):
    """Banque figée (avant le rename bank→institution de 0015)."""
    Bank = state.apps.get_model("accounts", "Bank")
    return Bank.objects.create(
        name=name or slug.upper(),
        slug=slug,
        country="CH",
        default_currency="CHF",
    )


def _make_account(state: ProjectState, *, bank, name: str, **extra):
    """Compte figé rattaché à une `Bank` (relation `bank`, pas `institution`)."""
    Account = state.apps.get_model("accounts", "Account")
    defaults: dict = {
        "bank": bank,
        "name": name,
        "account_type": "checking",
        "currency": "CHF",
    }
    defaults.update(extra)
    return Account.objects.create(**defaults)


def _make_user(state: ProjectState, *, email: str, is_active: bool = True):
    # CustomUser n'a PAS de champ username (AbstractUser.username = None) → email seul,
    # qui est l'USERNAME_FIELD unique.
    User = state.apps.get_model("users", "CustomUser")
    return User.objects.create(email=email, is_active=is_active)


# =========================================================================== #
# 0004 — Account.account_type : valeur stockée "current" → "checking"          #
# =========================================================================== #
class TestAccount0004CurrentToChecking:
    initial = ("accounts", "0003_savingsaccount")
    target = ("accounts", "0004_alter_account_account_type")

    def test_renames_current_value_to_checking(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        bank = _make_bank(old, slug="cic")
        # À l'état 0003, "current" est encore une valeur valide stockée en base.
        acc_cur = _make_account(old, bank=bank, name="Courant", account_type="current")
        acc_sav = _make_account(old, bank=bank, name="Épargne", account_type="savings")

        new = migrator.apply_tested_migration(self.target)
        Account = new.apps.get_model("accounts", "Account")

        assert Account.objects.get(pk=acc_cur.pk).account_type == "checking"
        # Les autres types ne sont pas touchés.
        assert Account.objects.get(pk=acc_sav.pk).account_type == "savings"

    def test_idempotent(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        bank = _make_bank(old, slug="cic")
        acc = _make_account(old, bank=bank, name="Courant", account_type="current")

        migrator.apply_tested_migration(self.target)
        # 2e passe : ré-appliquer la même migration (reset interne) ne casse rien.
        new = migrator.apply_tested_migration(self.target)
        Account = new.apps.get_model("accounts", "Account")
        assert Account.objects.get(pk=acc.pk).account_type == "checking"


# =========================================================================== #
# 0011 — copie CheckingAccount.iban → Account.iban                             #
# =========================================================================== #
class TestAccount0011CopyIban:
    initial = ("accounts", "0010_checkingaccount_iban_optional")
    target = ("accounts", "0011_account_iban")
    reverse = ("accounts", "0010_checkingaccount_iban_optional")

    def _seed(self, state):
        bank = _make_bank(state, slug="cic")
        acc = _make_account(state, bank=bank, name="Courant")
        CheckingAccount = state.apps.get_model("accounts", "CheckingAccount")
        # IBAN de test factice (jamais un vrai — SR-008).
        ca = CheckingAccount.objects.create(account=acc, iban="CH00TESTIBAN0011")
        return acc, ca

    def test_copies_iban_to_account(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        acc, _ = self._seed(old)
        # Un compte SANS CheckingAccount (donc sans iban legacy) reste à NULL.
        bank2 = _make_bank(old, slug="ubs")
        acc_no_ca = _make_account(old, bank=bank2, name="SansCA")

        new = migrator.apply_tested_migration(self.target)
        Account = new.apps.get_model("accounts", "Account")
        assert Account.objects.get(pk=acc.pk).iban == "CH00TESTIBAN0011"
        # Pas de CheckingAccount → rien à copier → Account.iban reste NULL.
        assert Account.objects.get(pk=acc_no_ca.pk).iban is None

    def test_empty_legacy_iban_is_not_copied(self, migrator):
        # CheckingAccount.iban="" (blank) → la garde `if ca.iban` empêche la copie :
        # Account.iban reste NULL plutôt que de devenir "".
        old = migrator.apply_initial_migration(self.initial)
        bank = _make_bank(old, slug="ubs")
        acc = _make_account(old, bank=bank, name="Courant")
        CheckingAccount = old.apps.get_model("accounts", "CheckingAccount")
        CheckingAccount.objects.create(account=acc, iban="")

        new = migrator.apply_tested_migration(self.target)
        Account = new.apps.get_model("accounts", "Account")
        assert Account.objects.get(pk=acc.pk).iban is None

    def test_reverse_removes_account_iban_field(self, migrator):
        # reverse = noop côté data, mais l'AddField se défait : le rollback retire bien
        # le champ Account.iban du schéma historique sans planter.
        migrator.apply_initial_migration(self.initial)
        migrator.apply_tested_migration(self.target)
        back = migrator.apply_tested_migration(self.reverse)
        Account = back.apps.get_model("accounts", "Account")
        assert "iban" not in [f.name for f in Account._meta.get_fields()]


# =========================================================================== #
# 0014 — assigne tous les users actifs comme membres de tous les comptes       #
# =========================================================================== #
class TestAccount0014MembersBackfill:
    initial = ("accounts", "0013_account_members")
    target = ("accounts", "0014_account_members_data")
    reverse = ("accounts", "0013_account_members")

    def test_assigns_active_users_to_all_accounts(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        bank = _make_bank(old, slug="cic")
        acc1 = _make_account(old, bank=bank, name="A1")
        acc2 = _make_account(old, bank=bank, name="A2")
        u_active = _make_user(old, email="active@test.dev", is_active=True)
        u_inactive = _make_user(old, email="inactive@test.dev", is_active=False)

        new = migrator.apply_tested_migration(self.target)
        Account = new.apps.get_model("accounts", "Account")

        for acc in (acc1, acc2):
            member_ids = set(
                Account.objects.get(pk=acc.pk).members.values_list("pk", flat=True)
            )
            # Seul l'utilisateur ACTIF est membre ; l'inactif est exclu.
            assert member_ids == {u_active.pk}
            assert u_inactive.pk not in member_ids

    def test_noop_when_no_users(self, migrator):
        # Base sans user (CI vierge) → la migration ne plante pas et ne crée rien.
        old = migrator.apply_initial_migration(self.initial)
        bank = _make_bank(old, slug="cic")
        acc = _make_account(old, bank=bank, name="Seul")

        new = migrator.apply_tested_migration(self.target)
        Account = new.apps.get_model("accounts", "Account")
        assert Account.objects.get(pk=acc.pk).members.count() == 0

    def test_reverse_clears_members(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        bank = _make_bank(old, slug="cic")
        acc = _make_account(old, bank=bank, name="A1")
        _make_user(old, email="u@test.dev", is_active=True)

        migrator.apply_tested_migration(self.target)
        back = migrator.apply_tested_migration(self.reverse)
        Account = back.apps.get_model("accounts", "Account")
        # Le reverse vide la table M2M (sans supprimer les comptes).
        assert Account.objects.get(pk=acc.pk).members.count() == 0


# =========================================================================== #
# 0018 — filet de sécurité CheckingAccount.iban → Account.iban + RemoveField   #
# =========================================================================== #
class TestAccount0018BackfillThenRemove:
    initial = ("accounts", "0017_institution_category")
    target = ("accounts", "0018_remove_checkingaccount_iban")
    reverse = ("accounts", "0017_institution_category")

    def test_backfills_residual_iban_before_removing_field(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        # NB : après 0015, la relation est `institution` (plus `bank`).
        Institution = old.apps.get_model("accounts", "Institution")
        inst = Institution.objects.create(
            name="UBS", slug="ubs", country="CH", default_currency="CHF"
        )
        Account = old.apps.get_model("accounts", "Account")
        acc = Account.objects.create(
            institution=inst, name="Courant", account_type="checking", currency="CHF"
        )
        CheckingAccount = old.apps.get_model("accounts", "CheckingAccount")
        # Account.iban NULL, mais le legacy CheckingAccount.iban est renseigné.
        CheckingAccount.objects.create(account=acc, iban="CH00RESIDUAL0018")

        new = migrator.apply_tested_migration(self.target)
        AccountNew = new.apps.get_model("accounts", "Account")
        CheckingNew = new.apps.get_model("accounts", "CheckingAccount")
        # Le résidu a été recopié vers Account.iban...
        assert AccountNew.objects.get(pk=acc.pk).iban == "CH00RESIDUAL0018"
        # ...et le champ legacy a disparu du schéma.
        assert "iban" not in [f.name for f in CheckingNew._meta.get_fields()]

    def test_reverse_restores_legacy_iban(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        Institution = old.apps.get_model("accounts", "Institution")
        inst = Institution.objects.create(
            name="UBS", slug="ubs", country="CH", default_currency="CHF"
        )
        Account = old.apps.get_model("accounts", "Account")
        acc = Account.objects.create(
            institution=inst,
            name="Courant",
            account_type="checking",
            currency="CHF",
            iban="CH00ONACCOUNT0018",
        )
        CheckingAccount = old.apps.get_model("accounts", "CheckingAccount")
        CheckingAccount.objects.create(account=acc, iban="")

        migrator.apply_tested_migration(self.target)
        back = migrator.apply_tested_migration(self.reverse)
        CheckingOld = back.apps.get_model("accounts", "CheckingAccount")
        # Le rollback re-crée le champ ET restaure Account.iban → CheckingAccount.iban.
        assert CheckingOld.objects.get(account_id=acc.pk).iban == "CH00ONACCOUNT0018"


# =========================================================================== #
# 0020 — backfill colour_hex (Account par-user, Institution global)            #
# =========================================================================== #
class TestAccount0020BackfillColourHex:
    initial = ("accounts", "0019_account_institution_colour_hex")
    target = ("accounts", "0020_backfill_colour_hex")
    reverse = ("accounts", "0019_account_institution_colour_hex")

    def test_allocates_colour_to_empty_rows_only(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        Institution = old.apps.get_model("accounts", "Institution")
        inst_empty = Institution.objects.create(
            name="UBS", slug="ubs", country="CH", default_currency="CHF", colour_hex=""
        )
        inst_set = Institution.objects.create(
            name="CIC",
            slug="cic",
            country="FR",
            default_currency="EUR",
            colour_hex="#ABCDEF",
        )
        Account = old.apps.get_model("accounts", "Account")
        User = old.apps.get_model("users", "CustomUser")
        user = User.objects.create(email="u@test.dev")
        acc_empty = Account.objects.create(
            institution=inst_empty,
            name="A1",
            account_type="checking",
            currency="CHF",
            colour_hex="",
        )
        acc_empty.members.set([user])
        acc_set = Account.objects.create(
            institution=inst_empty,
            name="A2",
            account_type="checking",
            currency="CHF",
            colour_hex="#123456",
        )
        acc_set.members.set([user])

        new = migrator.apply_tested_migration(self.target)
        AccountNew = new.apps.get_model("accounts", "Account")
        InstitutionNew = new.apps.get_model("accounts", "Institution")

        # Les lignes vides reçoivent une couleur ; les lignes déjà posées sont figées.
        assert AccountNew.objects.get(pk=acc_empty.pk).colour_hex != ""
        assert AccountNew.objects.get(pk=acc_set.pk).colour_hex == "#123456"
        assert InstitutionNew.objects.get(pk=inst_empty.pk).colour_hex != ""
        assert InstitutionNew.objects.get(pk=inst_set.pk).colour_hex == "#ABCDEF"

    def test_colour_is_deterministic_and_stable(self, migrator):
        # Idempotence : la migration ne touche que colour_hex="" → re-jouer ne change
        # pas une couleur déjà allouée.
        old = migrator.apply_initial_migration(self.initial)
        Institution = old.apps.get_model("accounts", "Institution")
        inst = Institution.objects.create(
            name="UBS", slug="ubs", country="CH", default_currency="CHF", colour_hex=""
        )

        new = migrator.apply_tested_migration(self.target)
        InstitutionNew = new.apps.get_model("accounts", "Institution")
        colour_first = InstitutionNew.objects.get(pk=inst.pk).colour_hex
        assert colour_first != ""

        again = migrator.apply_tested_migration(self.target)
        InstitutionAgain = again.apps.get_model("accounts", "Institution")
        assert InstitutionAgain.objects.get(pk=inst.pk).colour_hex == colour_first

    def test_reverse_clears_all_colours(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        Institution = old.apps.get_model("accounts", "Institution")
        Institution.objects.create(
            name="UBS", slug="ubs", country="CH", default_currency="CHF", colour_hex=""
        )

        migrator.apply_tested_migration(self.target)
        back = migrator.apply_tested_migration(self.reverse)
        InstitutionBack = back.apps.get_model("accounts", "Institution")
        # reverse remet colour_hex="" partout (annule le backfill).
        assert all(i.colour_hex == "" for i in InstitutionBack.objects.all())
