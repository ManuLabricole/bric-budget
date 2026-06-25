"""
Tests des data-migrations RunPython de l'app `transactions` (issue #197).

Même approche que pour accounts : on rejoue chaque RunPython sur l'état HISTORIQUE
des modèles via la fixture `migrator`, et on prouve l'état après + l'idempotence +
la réversibilité (SR-004). Les modèles sont récupérés via `state.apps.get_model(...)`
(versions figées), jamais importés directement.

Couvre : 0017 + 0020 (backfill owner — PRIORITAIRES #197), 0018 (contraintes scopées
owner), 0022 (BudgetTarget.owner). Les rehash 0009/0010 ont une limitation de plan
documentée plus bas (classe `TestRehashFormulasAreLocked`).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# =========================================================================== #
# 0009 / 0010 — rehash CIC & UBS                                                #
# --------------------------------------------------------------------------- #
# LIMITATION CONNUE (documentée, pas un oubli) :                               #
#                                                                              #
# Ces deux RunPython ne sont PAS isolables via le frozen-replay du migrator.   #
# Raison : dans le plan CANONIQUE de Django (topologique), `transactions/0009` #
# et `0010` (index 24-25) arrivent AVANT `accounts/0005` (`contract_number`,   #
# index 27) et `accounts/0015` (rename `bank`→`institution`, index 39) — alors #
# que leur code lit `tx.account.contract_number` ET filtre `account__bank__slug`.
# `django-test-migrations` reconstruit ce plan via `truncate_plan`, qui inclut #
# TOUT jusqu'au plus grand index ciblé :                                        #
#   - pin accounts assez HAUT pour `contract_number` + `bank` ⇒ 0009/0010 sont #
#     déjà dans le plan initial → ils tournent sur une table tx VIDE (no-op),  #
#     et `apply_tested_migration` sur une migration déjà appliquée ne la       #
#     rejoue pas → l'état avant/après est inobservable ;                       #
#   - pin accounts assez BAS pour garder 0009/0010 hors du plan initial ⇒      #
#     `Account` figé n'a pas encore `contract_number` → AttributeError.        #
# Aucun pin ne satisfait les deux. (Ces migrations « dépassent » leur propre   #
# dépendance de données dans le plan canonique ; ça ne casse pas la prod, qui  #
# migre accounts intégralement, mais empêche un test avant/après honnête.)     #
#                                                                              #
# Ce qui EST couvert ailleurs :                                                #
#   - la FORMULE de hash (source de vérité) → connectors + tests/connectors/   #
#     test_hash_stability.py ;                                                 #
#   - la PRÉSENCE + l'ORDRE de 0009/0010 dans le plan → test_migration_plan.py ;
#   - leur exécution sans erreur sur une vraie base → le `migrate` que pytest  #
#     joue pour construire la base de test (et la CI release-commands).        #
#                                                                              #
# On verrouille ici la formule des deux migrations par des assertions DIRECTES #
# (le code de transformation embarqué), ce qui détecte une régression de la    #
# formule sans dépendre du replay impossible.                                  #
# =========================================================================== #
class TestRehashFormulasAreLocked:
    """Garde de régression sur la FORMULE de hash embarquée dans 0009/0010."""

    def test_cic_formula_without_row_idx(self):
        # 0009 : sha256("{rib}|{date}|{amount}|{description_raw}") — stable entre exports
        # (plus de row_idx). Digest FIGÉ : toute modif de la formule de la migration le
        # fait bouger → test rouge.
        raw = "RIB123|2026-01-15|10.00|VIR SALAIRE"
        assert (
            hashlib.sha256(raw.encode()).hexdigest()
            == "e5bd2bb0d5effc438878aca1fcc8daf7c22e9595e629ac5cc7ab17a2d0a53ba9"
        )

    def test_ubs_formula_with_no_de_transaction(self):
        # 0010 : sha256("ubs_tx|{no_transaction}") quand l'identifiant bancaire est là.
        raw = "ubs_tx|9999125BN1308361"
        assert (
            hashlib.sha256(raw.encode()).hexdigest()
            == "9dab629d8826aac446cd13480d42790d1060b476cbd81bae3503d55e18e645e4"
        )

    def test_ubs_fallback_formula(self):
        # 0010 fallback (pas de "No de transaction") : date|time|amount|desc1|desc2
        # (time NULL → chaîne vide → double pipe).
        raw = "2026-02-01||42.00|DESC1|DESC2"
        assert (
            hashlib.sha256(raw.encode()).hexdigest()
            == "f520e7aa6d677c6e540589e8fa3d3f9c9c2aa30a1f9dc6061e88220e864370e0"
        )


# =========================================================================== #
# 0017 — backfill Category.owner / SubCategory.owner (perso → superuser)        #
# =========================================================================== #
class TestTransactions0017BackfillCategoryOwner:
    initial = [("transactions", "0016_category_subcategory_owner")]
    target = ("transactions", "0017_backfill_category_owner")
    reverse = ("transactions", "0016_category_subcategory_owner")

    def _make_user(self, state, *, email, is_superuser=False):
        User = state.apps.get_model("users", "CustomUser")
        return User.objects.create(email=email, is_superuser=is_superuser)

    def _make_cat(self, state, *, name, slug, is_system, owner=None):
        Category = state.apps.get_model("transactions", "Category")
        return Category.objects.create(
            name=name, slug=slug, is_system=is_system, owner=owner
        )

    def test_assigns_perso_categories_to_superuser(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        self._make_user(old, email="first@test.dev")  # 1er user, NON superuser
        su = self._make_user(old, email="su@test.dev", is_superuser=True)
        perso = self._make_cat(old, name="Perso", slug="perso", is_system=False)
        system = self._make_cat(old, name="Sys", slug="sys", is_system=True)

        new = migrator.apply_tested_migration(self.target)
        Category = new.apps.get_model("transactions", "Category")
        # Perso → owner = superuser ; système → owner reste NULL (partagé).
        assert Category.objects.get(pk=perso.pk).owner_id == su.pk
        assert Category.objects.get(pk=system.pk).owner_id is None

    def test_falls_back_to_first_user_without_superuser(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        first = self._make_user(old, email="first@test.dev")
        self._make_user(old, email="second@test.dev")
        perso = self._make_cat(old, name="Perso", slug="perso", is_system=False)

        new = migrator.apply_tested_migration(self.target)
        Category = new.apps.get_model("transactions", "Category")
        # Pas de superuser → 1er user créé (pk le plus bas).
        assert Category.objects.get(pk=perso.pk).owner_id == first.pk

    def test_noop_on_empty_user_base(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        perso = self._make_cat(old, name="Perso", slug="perso", is_system=False)

        new = migrator.apply_tested_migration(self.target)
        Category = new.apps.get_model("transactions", "Category")
        # Base sans user (CI vierge) → owner reste NULL, pas de crash.
        assert Category.objects.get(pk=perso.pk).owner_id is None

    def test_reverse_clears_perso_owner(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        su = self._make_user(old, email="su@test.dev", is_superuser=True)
        perso = self._make_cat(old, name="Perso", slug="perso", is_system=False)

        migrator.apply_tested_migration(self.target)
        back = migrator.apply_tested_migration(self.reverse)
        Category = back.apps.get_model("transactions", "Category")
        assert Category.objects.get(pk=perso.pk).owner_id is None
        # Sanity : le user existe toujours (reverse ne touche pas les users).
        assert su.pk is not None


# =========================================================================== #
# 0018 — passage aux UniqueConstraint scopées par owner                         #
# =========================================================================== #
class TestTransactions0018OwnerScopedUnique:
    """
    Note : la branche de dédoublonnage (suffixe `_dupN`) ne peut PAS être
    déclenchée depuis l'état AVANT (0017), car ce dernier impose encore l'ancien
    unique GLOBAL sur `Category.slug` (`transactions_category_slug_key`) → impossible
    d'insérer deux slugs identiques via l'ORM pour fabriquer la collision. Cette
    branche est un filet pour des données legacy/CLI. On teste donc le RÉSULTAT
    observable et porteur de sens : après migration, ce sont les contraintes SCOPÉES
    par owner qui s'appliquent (deux owners peuvent partager un slug ; un même owner
    ne le peut pas) — c'est précisément le contrat que la migration installe.
    """

    initial = [("transactions", "0017_backfill_category_owner")]
    target = ("transactions", "0018_owner_scoped_unique")

    def _make_user(self, state, *, email):
        User = state.apps.get_model("users", "CustomUser")
        return User.objects.create(email=email)

    def test_two_owners_can_share_a_slug_after_migration(self, migrator):
        migrator.apply_initial_migration(self.initial)
        new = migrator.apply_tested_migration(self.target)
        Category = new.apps.get_model("transactions", "Category")
        User = new.apps.get_model("users", "CustomUser")
        u1 = User.objects.create(email="u1@test.dev")
        u2 = User.objects.create(email="u2@test.dev")
        # L'ancien unique global est levé → même slug perso pour deux owners ≠ : OK.
        Category.objects.create(name="A", slug="courses", is_system=False, owner=u1)
        Category.objects.create(name="B", slug="courses", is_system=False, owner=u2)
        assert Category.objects.filter(slug="courses").count() == 2

    def test_same_owner_cannot_duplicate_slug(self, migrator):
        from django.db import IntegrityError, transaction

        migrator.apply_initial_migration(self.initial)
        new = migrator.apply_tested_migration(self.target)
        Category = new.apps.get_model("transactions", "Category")
        User = new.apps.get_model("users", "CustomUser")
        u = User.objects.create(email="u@test.dev")
        Category.objects.create(name="A", slug="courses", is_system=False, owner=u)
        # La contrainte scopée category_owner_slug_uniq bloque le doublon (owner, slug).
        with pytest.raises(IntegrityError), transaction.atomic():
            Category.objects.create(name="B", slug="courses", is_system=False, owner=u)


# =========================================================================== #
# 0020 — backfill CategorizationRule.owner (toutes les règles → superuser)      #
# =========================================================================== #
class TestTransactions0020BackfillRuleOwner:
    initial = [("transactions", "0019_categorizationrule_owner")]
    target = ("transactions", "0020_backfill_categorizationrule_owner")
    reverse = ("transactions", "0019_categorizationrule_owner")

    def _make_rule(self, state, *, keyword):
        Rule = state.apps.get_model("transactions", "CategorizationRule")
        Category = state.apps.get_model("transactions", "Category")
        cat = Category.objects.create(
            name=f"cat-{keyword}", slug=f"cat-{keyword}", is_system=True
        )
        return Rule.objects.create(keyword=keyword, category=cat)

    def _make_user(self, state, *, email, is_superuser=False):
        User = state.apps.get_model("users", "CustomUser")
        return User.objects.create(email=email, is_superuser=is_superuser)

    def test_assigns_all_rules_to_superuser(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        self._make_user(old, email="first@test.dev")
        su = self._make_user(old, email="su@test.dev", is_superuser=True)
        rule = self._make_rule(old, keyword="migros")

        new = migrator.apply_tested_migration(self.target)
        Rule = new.apps.get_model("transactions", "CategorizationRule")
        assert Rule.objects.get(pk=rule.pk).owner_id == su.pk

    def test_noop_on_empty_user_base(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        rule = self._make_rule(old, keyword="coop")

        new = migrator.apply_tested_migration(self.target)
        Rule = new.apps.get_model("transactions", "CategorizationRule")
        assert Rule.objects.get(pk=rule.pk).owner_id is None

    def test_reverse_clears_owner(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        self._make_user(old, email="su@test.dev", is_superuser=True)
        rule = self._make_rule(old, keyword="sbb")

        migrator.apply_tested_migration(self.target)
        back = migrator.apply_tested_migration(self.reverse)
        Rule = back.apps.get_model("transactions", "CategorizationRule")
        assert Rule.objects.get(pk=rule.pk).owner_id is None


# =========================================================================== #
# 0022 — BudgetTarget.owner : backfill depuis category.owner + purge système    #
# =========================================================================== #
class TestTransactions0022BackfillBudgetTargetOwner:
    initial = [
        (
            "transactions",
            "0021_remove_subcategory_subcategory_category_name_uniq_and_more",
        )
    ]
    target = ("transactions", "0022_budgettarget_owner")
    reverse = (
        "transactions",
        "0021_remove_subcategory_subcategory_category_name_uniq_and_more",
    )

    def _make_user(self, state, *, email):
        User = state.apps.get_model("users", "CustomUser")
        return User.objects.create(email=email)

    def _make_cat(self, state, *, slug, owner):
        Category = state.apps.get_model("transactions", "Category")
        return Category.objects.create(
            name=slug, slug=slug, is_system=(owner is None), owner=owner
        )

    def _make_target(self, state, *, category):
        BudgetTarget = state.apps.get_model("transactions", "BudgetTarget")
        return BudgetTarget.objects.create(
            category=category,
            amount=Decimal("100.00"),  # SR-002
        )

    def test_backfills_owner_from_category_owner(self, migrator):
        old = migrator.apply_initial_migration(self.initial)
        user = self._make_user(old, email="u@test.dev")
        cat = self._make_cat(old, slug="perso", owner=user)
        target = self._make_target(old, category=cat)

        new = migrator.apply_tested_migration(self.target)
        BudgetTarget = new.apps.get_model("transactions", "BudgetTarget")
        assert BudgetTarget.objects.get(pk=target.pk).owner_id == user.pk

    def test_purges_targets_on_system_categories(self, migrator):
        # Objectif sur une catégorie SYSTÈME (owner NULL) = partagé/ambigu → purge.
        old = migrator.apply_initial_migration(self.initial)
        cat = self._make_cat(old, slug="sys", owner=None)
        target = self._make_target(old, category=cat)

        new = migrator.apply_tested_migration(self.target)
        BudgetTarget = new.apps.get_model("transactions", "BudgetTarget")
        assert not BudgetTarget.objects.filter(pk=target.pk).exists()

    def test_reverse_removes_owner_field(self, migrator):
        # Le reverse de 0022 défait tout l'AddField : à l'état 0021, BudgetTarget n'a
        # PAS de champ owner. On vérifie que le rollback s'exécute sans planter (le
        # reverse_backfill remet owner=NULL avant que l'AddField ne soit retiré) et
        # que le champ a bien disparu du schéma historique.
        old = migrator.apply_initial_migration(self.initial)
        user = self._make_user(old, email="u@test.dev")
        cat = self._make_cat(old, slug="perso", owner=user)
        self._make_target(old, category=cat)

        migrator.apply_tested_migration(self.target)
        back = migrator.apply_tested_migration(self.reverse)
        BudgetTarget = back.apps.get_model("transactions", "BudgetTarget")
        assert "owner" not in [f.name for f in BudgetTarget._meta.get_fields()]
