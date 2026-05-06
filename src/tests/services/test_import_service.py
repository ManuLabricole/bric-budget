"""
tests/services/test_import_service.py — Tests de l'ImportService.

Ces tests requièrent une base de données (PostgreSQL via make up).
Décorateur @pytest.mark.django_db sur chaque test qui touche la DB.

Ce qu'on teste ici — les 4 responsabilités critiques de l'ImportService :

1. DÉDUPLICATION FILE  : même file_hash → erreur propre, rien écrit
2. DÉDUPLICATION ROW   : même import_hash dans un autre fichier → skipped
3. AMOUNT_CHF CHF      : account.currency=CHF → amount_chf = amount (identiques)
4. AMOUNT_CHF EUR      : account.currency=EUR → amount_chf = amount × taux
5. AMOUNT_CHF FALLBACK : taux indisponible (API down) → amount_chf=None, import OK
6. FIND_RULE           : keyword match sur description_raw ou merchant_name
7. FIND_RULE CASE      : matching case-insensitive
8. FIND_RULE EMPTY     : pas de règle → None (pas de DB requis pour ce cas)

On n'utilise PAS la fixture de vrai fichier CSV/Excel ici — ImportService reçoit
une liste de TransactionDict déjà parsée. Les tests de parsing vivent dans test_yuh.py,
test_ubs.py, test_cic.py. Cette séparation garantit qu'un bug de parsing ne masque
pas un bug du service, et vice versa.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# On importe les helpers depuis le conftest local
from tests.services.conftest import make_file_hash, make_tx
from transactions.models import CategorizationRule, Category, Transaction
from transactions.services import ImportService

# =============================================================================
# 1. Déduplication FILE — même file_hash
# =============================================================================


@pytest.mark.django_db
def test_same_file_imported_twice_returns_error(chf_account, user):
    """
    ImportService.run() vérifie ImportLog.file_hash avant tout traitement.
    Si le fichier exact a déjà été importé → count_errors=1, rien écrit.

    Pourquoi c'est important : sans cette garde, un utilisateur qui ré-importe
    par erreur le même fichier doublerait toutes ses transactions.
    """
    service = ImportService()
    transactions = [make_tx("seed1")]
    file_hash = make_file_hash("file_a")

    # Premier import : OK
    result1 = service.run(transactions, chf_account, user, "export.csv", file_hash)
    assert result1.count_created == 1
    assert result1.count_errors == 0

    # Deuxième import avec le même file_hash : bloqué
    result2 = service.run(transactions, chf_account, user, "export.csv", file_hash)
    assert result2.count_errors == 1
    assert result2.count_created == 0
    assert "already imported" in result2.error_detail[0]


# =============================================================================
# 2. Déduplication ROW — même import_hash dans un autre fichier
# =============================================================================


@pytest.mark.django_db
def test_duplicate_transaction_hash_is_skipped(chf_account, user):
    """
    Même import_hash dans un fichier différent → transaction skippée silencieusement.

    Scénario réel : on ré-exporte Yuh sur une période qui chevauche un import précédent.
    Les transactions en double sont détectées par import_hash et ignorées.
    count_skipped est incrémenté pour que l'utilisateur soit informé.
    """
    service = ImportService()
    tx = make_tx("row_seed")

    # Import 1 : tx créée
    result1 = service.run([tx], chf_account, user, "file1.csv", make_file_hash("f1"))
    assert result1.count_created == 1

    # Import 2 : même tx, file_hash différent → créée=0, skipped=1
    result2 = service.run([tx], chf_account, user, "file2.csv", make_file_hash("f2"))
    assert result2.count_created == 0
    assert result2.count_skipped == 1

    # Vérification DB : 1 seule transaction, pas de doublon
    assert Transaction.objects.count() == 1


# =============================================================================
# 3. amount_chf — compte CHF
# =============================================================================


@pytest.mark.django_db
def test_amount_chf_equals_amount_for_chf_account(chf_account, user):
    """
    Pour un compte CHF, amount_chf = amount (pas de conversion).

    C'est la branche simple dans _build_transaction :
        if account.currency == "CHF":
            amount_chf = amount
    Aucun appel à get_exchange_rate().
    """
    service = ImportService()
    tx = make_tx("chf_seed", amount=-50.0, currency="CHF")
    service.run([tx], chf_account, user, "file.csv", make_file_hash("fx"))

    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    # Decimal("-50.0") == Decimal("-50.00") → True (égalité de valeur)
    assert saved.amount_chf == Decimal("-50.0")
    assert saved.amount == Decimal("-50.0")


# =============================================================================
# 4. amount_chf — compte EUR avec taux disponible
# =============================================================================


@pytest.mark.django_db
def test_amount_chf_calculated_from_exchange_rate(eur_account, user):
    """
    Pour un compte EUR, amount_chf = amount × taux_EUR_CHF.

    On mocke get_exchange_rate pour éviter un appel réseau vers frankfurter.app.
    Le mock retourne Decimal("0.93") → -100 EUR × 0.93 = -93.00 CHF.

    Pourquoi mocker ?
    → Les tests doivent être déterministes et indépendants du réseau.
       Si l'API est down, les tests ne doivent pas échouer.
    """
    service = ImportService()
    tx = make_tx("eur_seed", amount=-100.0, currency="EUR")

    with patch("transactions.services.get_exchange_rate", return_value=Decimal("0.93")):
        service.run([tx], eur_account, user, "file.csv", make_file_hash("eur"))

    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.amount_chf == Decimal("-93.00")


# =============================================================================
# 5. amount_chf — fallback quand le taux est indisponible
# =============================================================================


@pytest.mark.django_db
def test_amount_chf_is_none_when_rate_unavailable(eur_account, user):
    """
    Si get_exchange_rate() retourne None (API down, erreur réseau...),
    amount_chf reste None MAIS la transaction est quand même créée.

    Comportement "best effort" : mieux avoir une transaction sans montant CHF
    que de perdre la transaction entière. On peut backfiller amount_chf plus tard.
    """
    service = ImportService()
    tx = make_tx("eur_none_seed", amount=-100.0, currency="EUR")

    with patch("transactions.services.get_exchange_rate", return_value=None):
        result = service.run(
            [tx], eur_account, user, "file.csv", make_file_hash("none")
        )

    assert result.count_created == 1
    assert result.count_errors == 0

    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.amount_chf is None


# =============================================================================
# 6. _find_rule() — matching description_raw
# =============================================================================


@pytest.mark.django_db
def test_find_rule_matches_keyword_in_description_raw(db):
    """
    Règle sur description_raw : keyword 'migros' dans 'MIGROS LAUSANNE' → match.

    target_field="description_raw" → on cherche dans le texte brut de la banque.
    C'est le target_field conseillé dans le wizard de règles (plus fiable que
    merchant_name qui peut être edité manuellement).
    """
    category = Category.objects.create(name="Food", slug="food")
    rule = CategorizationRule.objects.create(
        category=category,
        keyword="migros",
        target_field=CategorizationRule.TargetField.DESCRIPTION_RAW,
        priority=1,
        is_active=True,
    )

    service = ImportService()
    tx = {
        "description_raw": "MIGROS LAUSANNE",
        "merchant_name": "Migros Lausanne",
        "display_name": "Migros Lausanne",
    }
    assert service._find_rule(tx, [rule]) == rule


@pytest.mark.django_db
def test_find_rule_matches_keyword_in_merchant_name(db):
    """
    Règle sur merchant_name (legacy) : keyword 'coop' dans display_name → match.

    merchant_name est un alias de display_name depuis Phase 2G — _find_rule
    utilise display_name pour les deux.
    """
    category = Category.objects.create(name="Grocery", slug="grocery")
    rule = CategorizationRule.objects.create(
        category=category,
        keyword="coop",
        target_field=CategorizationRule.TargetField.MERCHANT_NAME,
        priority=1,
        is_active=True,
    )

    service = ImportService()
    tx = {
        "description_raw": "COOP 2347 LAUSANNE VD",
        "merchant_name": "Coop Lausanne",
        "display_name": "Coop Lausanne",
    }
    assert service._find_rule(tx, [rule]) == rule


@pytest.mark.django_db
def test_find_rule_is_case_insensitive(db):
    """
    Le matching est case-insensitive : 'MIGROS' matche 'migros lausanne'.

    Implémentation : rule.keyword.lower() in text.lower()
    """
    category = Category.objects.create(name="Food 2", slug="food-2")
    rule = CategorizationRule.objects.create(
        category=category,
        keyword="MIGROS",
        target_field=CategorizationRule.TargetField.DESCRIPTION_RAW,
        priority=1,
        is_active=True,
    )

    service = ImportService()
    tx = {
        "description_raw": "migros lausanne",
        "merchant_name": "Migros",
        "display_name": "Migros",
    }
    assert service._find_rule(tx, [rule]) == rule


def test_find_rule_returns_none_for_empty_rules_list():
    """
    Aucune règle active → None (la transaction restera 'Unknown').

    Ce test n'a PAS besoin de la DB : on passe une liste vide directement.
    Aucun décorateur @pytest.mark.django_db → exécution plus rapide.
    """
    service = ImportService()
    tx = {
        "description_raw": "RANDOM SHOP",
        "merchant_name": "Random Shop",
        "display_name": "Random Shop",
    }
    assert service._find_rule(tx, []) is None


def test_find_rule_no_match_returns_none():
    """
    Règle existante mais keyword absent de la transaction → None.

    On utilise SimpleNamespace pour simuler une règle sans accès à la DB.
    """
    service = ImportService()
    rule = SimpleNamespace(keyword="migros", target_field="description_raw")
    tx = {
        "description_raw": "SNCF PARIS",
        "merchant_name": "Sncf Paris",
        "display_name": "Sncf Paris",
    }
    assert service._find_rule(tx, [rule]) is None


# =============================================================================
# 7. dry_run — prévisualisation sans écriture
# =============================================================================


@pytest.mark.django_db
def test_dry_run_does_not_write_to_database(chf_account, user):
    """
    dry_run=True : les comptes sont corrects MAIS aucune Transaction n'est écrite.

    Utilisé par les commandes d'import pour afficher un rapport avant confirmation.
    Le count_created reflète ce qui SERAIT écrit, pas ce qui a été écrit.
    """
    service = ImportService()
    transactions = [make_tx("dry1"), make_tx("dry2")]
    result = service.run(
        transactions,
        chf_account,
        user,
        "file.csv",
        make_file_hash("dry"),
        dry_run=True,
    )

    assert result.count_created == 2
    assert Transaction.objects.count() == 0  # rien en DB
