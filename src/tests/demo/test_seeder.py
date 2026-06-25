"""
tests/demo/test_seeder.py — seed_demo() passe par le VRAI pipeline d'import (#118).

On prouve : user loginable, comptes + carte, ImportLog réels avec transactions
liées + fichier chiffré stocké, idempotence (dédup file_hash), flush, reset.
Le stockage est redirigé en tmp (pas de pollution de assets/private/).
"""

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model

from accounts.models import Account, BalanceSnapshot, Card
from demo.seeder import reset_demo, seed_demo
from transactions.models import (
    CategorizationRule,
    Category,
    ImportLog,
    SubCategory,
    Transaction,
)


@pytest.fixture
def demo_env(settings, tmp_path):
    """Creds + stockage isolés pour ne pas toucher la vraie config ni assets/."""
    settings.DEMO_USER_EMAIL = "demo-test@bric.test"
    settings.DEMO_USER_PASSWORD = "test-demo-pwd"
    settings.IMPORT_STORAGE_ROOT = tmp_path / "imports"
    settings.IMPORT_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return settings


@pytest.mark.django_db
def test_seed_demo_via_real_pipeline(demo_env):
    summary = seed_demo(months=3)

    user_model = get_user_model()
    user = user_model.objects.get(email=demo_env.DEMO_USER_EMAIL)
    # User loginable avec les creds .env
    assert user.check_password("test-demo-pwd")
    assert summary.user_email == demo_env.DEMO_USER_EMAIL

    # 6 comptes : UBS (courant+épargne), CIC (courant+livret EUR), Yuh (courant+épargne)
    assert Account.objects.filter(members=user).count() == 6
    assert Account.objects.filter(members=user, currency="EUR").count() == 2  # CIC
    assert Card.objects.filter(
        checking_account__account__members=user, last_four="1150"
    ).exists()

    # Imports via pipeline → ImportLog réels (≥5 fichiers, CIC = 2 feuilles)
    assert ImportLog.objects.filter(account__members=user).count() >= 5
    txs = Transaction.objects.filter(account__members=user)
    assert txs.count() > 30
    assert not txs.filter(import_log__isnull=True).exists()
    # Chaque compte a importé des transactions (régression import_hash inter-comptes :
    # l'épargne UBS importait 0 tx car elle réutilisait les No de transaction du courant).
    assert not ImportLog.objects.filter(account__members=user, count_created=0).exists()

    # Fichier source CHIFFRÉ stocké : prouver le chiffrement, pas juste la persistance.
    # (Un .exists() sur stored_path ne prouvait que « un fichier a été écrit », pas qu'il
    # était chiffré → le test passait même si is_encrypted=False.)
    stored = ImportLog.objects.filter(account__members=user).exclude(stored_path="")
    assert stored.exists()
    assert not stored.filter(is_encrypted=False).exists()

    # CHAQUE compte a au moins un BalanceSnapshot → visible en patrimoine.
    # (Régression : Yuh n'a pas de solde dans son CSV → était invisible.)
    account_ids = list(
        Account.objects.filter(members=user).values_list("id", flat=True)
    )
    accounts_with_snapshot = (
        BalanceSnapshot.objects.filter(account_id__in=account_ids)
        .values("account_id")
        .distinct()
        .count()
    )
    assert accounts_with_snapshot == 6

    # Catégorisation : règles démo seedées + appliquées à l'import
    assert CategorizationRule.objects.unscoped().filter(owner=user).count() >= 10
    assert not txs.filter(category__isnull=True).exists()  # toutes ont une catégorie
    assert txs.exclude(category__slug="inconnu").exists()  # certaines via les règles
    assert txs.filter(is_internal_transfer=True).exists()  # virements épargne détectés

    # Catégories perso seedées pour le user démo (montre la feature, scopées owner).
    # DB de test = fraîche → les 11 PersoCat passent (1 top-level + 10 sous-cats).
    assert Category.objects.unscoped().filter(owner=user, is_system=False).count() == 1
    assert (
        SubCategory.objects.unscoped().filter(owner=user, is_system=False).count() == 10
    )
    # Dont une sous-cat perso sous une catégorie SYSTÈME (le cas qui fuyait avant #118).
    assert (
        SubCategory.objects.unscoped()
        .filter(owner=user, name="Concert", category__is_system=True)
        .exists()
    )


@pytest.mark.django_db
def test_seed_demo_idempotent_same_day(demo_env):
    seed_demo(months=2)
    user = get_user_model().objects.get(email=demo_env.DEMO_USER_EMAIL)
    count1 = Transaction.objects.filter(account__members=user).count()

    seed_demo(months=2)  # re-run même jour → dédup file_hash, rien de neuf

    count2 = Transaction.objects.filter(account__members=user).count()
    assert count2 == count1


@pytest.mark.django_db
def test_flush_reseeds_same_volume(demo_env):
    seed_demo(months=2)
    user = get_user_model().objects.get(email=demo_env.DEMO_USER_EMAIL)
    before = Transaction.objects.filter(account__members=user).count()

    seed_demo(months=2, flush=True)  # flush + re-seed → même volume

    after = Transaction.objects.filter(account__members=user).count()
    assert after == before


@pytest.mark.django_db
def test_reseed_adopts_pre_is_demo_accounts_without_integrity_error(demo_env):
    """Régression : une DB seedée AVANT le marqueur is_demo (#202) a des comptes
    is_demo=False. Le re-seed doit les ADOPTER (matching par IBAN/RIB synthétique,
    cf. _ensure_accounts) et NON tenter un INSERT en doublon d'IBAN — sinon
    `IntegrityError: duplicate key "accounts_account_iban_key"` (bug remonté par le
    bouton Seed de l'admin sur une DB de dev existante)."""
    seed_demo(months=2)
    user = get_user_model().objects.get(email=demo_env.DEMO_USER_EMAIL)
    # Simule l'état pré-#202 : les comptes existent mais sans le marqueur démo.
    Account.objects.filter(members=user).update(is_demo=False)
    ubs_ibans = set(
        Account.objects.filter(institution__slug="ubs").values_list("iban", flat=True)
    )

    # Ne doit PAS lever IntegrityError (le bug : duplicate key sur l'IBAN).
    seed_demo(months=2, flush=True)

    # Comptes à identifiant synthétique (UBS iban, CIC contract_number) : ADOPTÉS,
    # pas dupliqués, et re-marqués is_demo=True (auto-heal).
    ubs = Account.objects.filter(institution__slug="ubs")
    assert ubs.count() == 2  # adoptés par IBAN → aucun doublon
    assert not ubs.filter(is_demo=False).exists()  # auto-heal
    assert set(ubs.values_list("iban", flat=True)) == ubs_ibans  # mêmes comptes
    cic = Account.objects.filter(institution__slug="cic")
    assert cic.count() == 2  # adoptés par (institution, contract_number)
    assert not cic.filter(is_demo=False).exists()

    # Yuh (sans identifiant) : garde #202 ASSUMÉE > idempotence. Les comptes Yuh
    # pré-#202 (is_demo=False) ne sont PAS adoptés — le fallback exige is_demo=True,
    # pour ne jamais happer le compte d'un homonyme réel (cf. #202). On vérifie cette
    # propriété de SÉCURITÉ (et non un count==2 qui exigerait de relâcher la garde) :
    # les 2 Yuh d'origine restent intacts ; la migration sûre est un re-flag manuel.
    assert Account.objects.filter(institution__slug="yuh", is_demo=False).count() == 2


@pytest.mark.django_db
def test_reset_demo_wipes_data_keeps_user(demo_env):
    seed_demo(months=2)
    user_model = get_user_model()
    user = user_model.objects.get(email=demo_env.DEMO_USER_EMAIL)
    assert Account.objects.filter(members=user).exists()

    reset_demo()

    # #202 : reset_demo cible désormais is_demo=True (marqueur déterministe) — on teste
    # ce vrai invariant, pas members=user (qui passerait par coïncidence).
    assert not Account.objects.filter(is_demo=True).exists()
    assert not Account.objects.filter(members=user).exists()
    assert not Transaction.objects.filter(account__members=user).exists()
    assert user_model.objects.filter(email=demo_env.DEMO_USER_EMAIL).exists()
