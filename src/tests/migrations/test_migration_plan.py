"""
Garde de CONFORMITÉ des migrations (issue #197).

Deux verrous indépendants de la logique métier :

1. ORDRE du plan — `django_test_migrations.plan.all_migrations` rejoue le plan
   topologique réel. On verrouille l'ordre RELATIF des data-migrations clés (les
   RunPython de backfill/rehash) : un réordonnancement accidentel (dépendance
   oubliée, migration insérée au mauvais endroit) casse le test. On vérifie aussi
   que chaque RunPython attendu est bien PRÉSENT dans le plan.

2. DÉRIVE modèle ↔ migration — `makemigrations --check --dry-run` échoue si un
   champ/contrainte a changé sur un modèle sans migration générée. Doublé en CI
   (job `test`), mais aussi ici pour un retour local immédiat.

Pourquoi pas de @pytest.mark.django_db sur le test d'ordre ? `all_migrations` lit le
graphe de migrations (fichiers), pas la base — aucun accès DB requis.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django_test_migrations.plan import all_migrations, nodes_to_tuples


# Les 12 RunPython recensés (#197). On vérifie leur PRÉSENCE dans le plan : si l'un
# disparaît ou est renommé sans transition, la garde tombe.
EXPECTED_RUNPYTHON_MIGRATIONS = {
    ("accounts", "0004_alter_account_account_type"),
    ("accounts", "0011_account_iban"),
    ("accounts", "0014_account_members_data"),
    ("accounts", "0018_remove_checkingaccount_iban"),
    ("accounts", "0020_backfill_colour_hex"),
    ("transactions", "0004_budgettarget_remove_period"),
    ("transactions", "0009_rehash_cic_transactions"),
    ("transactions", "0010_rehash_ubs_transactions"),
    ("transactions", "0017_backfill_category_owner"),
    ("transactions", "0018_owner_scoped_unique"),
    ("transactions", "0020_backfill_categorizationrule_owner"),
    ("transactions", "0022_budgettarget_owner"),
}


def _plan_tuples() -> list[tuple[str, str]]:
    """Plan complet (ordre topologique) sous forme [(app, name), ...]."""
    return nodes_to_tuples(all_migrations("default"))


@pytest.mark.django_db
class TestMigrationPlan:
    # all_migrations() lit le graphe via MigrationLoader, qui ouvre la connexion DB
    # (état appliqué) → marque django_db requise même si on ne fait pas de requête métier.
    def test_all_runpython_migrations_present(self):
        plan = set(_plan_tuples())
        missing = EXPECTED_RUNPYTHON_MIGRATIONS - plan
        assert not missing, f"Data-migrations RunPython absentes du plan : {missing}"

    def test_relative_order_of_key_data_migrations(self):
        plan = _plan_tuples()
        index = {node: i for i, node in enumerate(plan)}

        # Le rehash CIC (0009) précède le rehash UBS (0010).
        assert (
            index[("transactions", "0009_rehash_cic_transactions")]
            < index[("transactions", "0010_rehash_ubs_transactions")]
        )
        # owner : AddField (0016) → backfill Category (0017) → contraintes scopées (0018).
        assert (
            index[("transactions", "0016_category_subcategory_owner")]
            < index[("transactions", "0017_backfill_category_owner")]
            < index[("transactions", "0018_owner_scoped_unique")]
        )
        # CategorizationRule.owner : AddField (0019) → backfill (0020).
        assert (
            index[("transactions", "0019_categorizationrule_owner")]
            < index[("transactions", "0020_backfill_categorizationrule_owner")]
        )
        # accounts : ajout colour_hex (0019) → backfill colour_hex (0020).
        assert (
            index[("accounts", "0019_account_institution_colour_hex")]
            < index[("accounts", "0020_backfill_colour_hex")]
        )
        # Le rename bank→institution (0015) vient APRÈS les rehash qui lisent `bank`
        # (0009/0010) — invariant qui explique la limitation de test documentée.
        assert (
            index[("transactions", "0010_rehash_ubs_transactions")]
            < index[("accounts", "0015_rename_bank_institution")]
        )


class TestNoModelDrift:
    """`makemigrations --check` : modèle modifié sans migration ⇒ échec (CI rouge)."""

    @pytest.mark.django_db
    def test_no_missing_migrations(self):
        out = StringIO()
        # --check : exit non-zéro (SystemExit) s'il manque une migration.
        # --dry-run : n'écrit aucun fichier. On ne veut PAS de SystemExit ici.
        try:
            call_command(
                "makemigrations", "--check", "--dry-run", stdout=out, stderr=out
            )
        except SystemExit as exc:  # pragma: no cover - ne se déclenche qu'en dérive
            pytest.fail(
                "Dérive modèle↔migration détectée — `makemigrations` a des "
                f"changements non générés :\n{out.getvalue()}\n(code={exc.code})"
            )
