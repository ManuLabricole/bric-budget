"""
tests/services/test_import_storage.py — Tests unitaires pour imports/storage.py.

Ces tests couvrent :
    - La convention de nommage (build_import_filename)
    - Le chiffrement / déchiffrement Fernet (encrypt_bytes / decrypt_bytes)
    - La sauvegarde sur disque (save_import_file)

Aucun accès DB requis pour ces tests — pas de fixture db.
Les tests de sauvegarde utilisent pytest's tmp_path pour éviter tout effet de bord.

Clé de test :
    On utilise @override_settings avec une clé Fernet générée en dur pour les
    tests (jamais la clé de production). Même clé pour toute la session de test.
"""

from datetime import date
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from django.test import override_settings

# Clé Fernet stable pour les tests — générée une fois, hardcodée ici.
# Ce n'est PAS la clé de production. Elle est publique par définition (commit).
# Son rôle : permettre aux tests de tourner sans variable d'environnement.
TEST_FERNET_KEY = Fernet.generate_key().decode()


# =============================================================================
# build_import_filename — Convention de nommage
# =============================================================================


class TestBuildImportFilename:
    """Tests de la fonction build_import_filename."""

    def test_single_account_full(self):
        """Cas nominal : un seul compte, avec dates, balance et transactions."""
        from imports.storage import build_import_filename

        result = build_import_filename(
            institution_slug="yuh",
            account_names=["checking"],
            date_min=date(2026, 1, 1),
            date_max=date(2026, 4, 30),
            balance=Decimal("12345.67"),
            n_transactions=42,
            original_ext=".csv",
        )
        assert result == "yuh_checking_20260101_20260430_b12345.67_42tx.csv"

    def test_multi_account_uses_multi_label(self):
        """CIC multi-feuilles : plusieurs comptes → 'multi' dans le nom."""
        from imports.storage import build_import_filename

        result = build_import_filename(
            institution_slug="cic",
            account_names=["compte_courant", "livret_a"],
            date_min=date(2026, 1, 1),
            date_max=date(2026, 4, 30),
            balance=None,
            n_transactions=5,
            original_ext=".xlsx",
        )
        assert result == "cic_multi_20260101_20260430_5tx.xlsx"

    def test_no_balance_omits_balance_part(self):
        """Balance absente → pas de '_b{balance}' dans le nom."""
        from imports.storage import build_import_filename

        result = build_import_filename(
            institution_slug="ubs",
            account_names=["compte_courant"],
            date_min=date(2026, 2, 1),
            date_max=date(2026, 4, 30),
            balance=None,
            n_transactions=15,
            original_ext=".csv",
        )
        assert result == "ubs_compte_courant_20260201_20260430_15tx.csv"
        assert "_b" not in result

    def test_no_dates_uses_nodate_fallback(self):
        """Sans dates (all skipped → aucune tx en DB) → 'nodate' dans le nom."""
        from imports.storage import build_import_filename

        result = build_import_filename(
            institution_slug="yuh",
            account_names=["checking"],
            date_min=None,
            date_max=None,
            balance=None,
            n_transactions=0,
            original_ext=".csv",
        )
        assert result == "yuh_checking_nodate_nodate_0tx.csv"

    def test_extension_without_leading_dot(self):
        """L'extension sans point de tête est aussi acceptée."""
        from imports.storage import build_import_filename

        result = build_import_filename(
            institution_slug="yuh",
            account_names=["checking"],
            date_min=date(2026, 1, 1),
            date_max=date(2026, 1, 31),
            balance=None,
            n_transactions=10,
            original_ext="csv",  # sans le point
        )
        assert result.endswith(".csv")
        assert not result.endswith("..csv")

    def test_zero_transactions_still_valid(self):
        """0 transactions est un cas valide (import "sync status")."""
        from imports.storage import build_import_filename

        result = build_import_filename(
            institution_slug="yuh",
            account_names=["checking"],
            date_min=date(2026, 1, 1),
            date_max=date(2026, 1, 31),
            balance=Decimal("5000.00"),
            n_transactions=0,
            original_ext=".csv",
        )
        assert "_0tx." in result


# =============================================================================
# encrypt_bytes / decrypt_bytes — Chiffrement Fernet
# =============================================================================


class TestEncryptDecrypt:
    """Tests du roundtrip chiffrement/déchiffrement."""

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_roundtrip(self):
        """Chiffrer puis déchiffrer redonne les données originales."""
        from imports.storage import decrypt_bytes, encrypt_bytes

        original = b"montant,date,description\n100.00,2026-03-17,MIGROS"
        ciphertext = encrypt_bytes(original)

        # Le ciphertext est différent de l'original (vérification de base)
        assert ciphertext != original
        # Déchiffrement → données identiques
        assert decrypt_bytes(ciphertext) == original

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_ciphertext_differs_each_call(self):
        """Deux chiffrements du même contenu donnent des ciphertexts différents.
        Fernet inclut un IV aléatoire → pas de déterminisme."""
        from imports.storage import encrypt_bytes

        data = b"same data"
        assert encrypt_bytes(data) != encrypt_bytes(data)

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_decrypt_wrong_key_raises(self):
        """Déchiffrement avec une mauvaise clé lève InvalidToken."""
        from cryptography.fernet import InvalidToken

        from imports.storage import encrypt_bytes

        data = b"sensitive financial data"
        ciphertext = encrypt_bytes(data)

        # Tenter de déchiffrer avec une clé différente
        other_key = Fernet.generate_key().decode()
        with override_settings(IMPORT_ENCRYPTION_KEY=other_key):
            from imports.storage import decrypt_bytes

            with pytest.raises(InvalidToken):
                decrypt_bytes(ciphertext)

    @override_settings(IMPORT_ENCRYPTION_KEY="")
    def test_missing_key_raises_improperly_configured(self):
        """Clé absente → ImproperlyConfigured (pas un crash silencieux)."""
        from django.core.exceptions import ImproperlyConfigured

        from imports.storage import encrypt_bytes

        with pytest.raises(ImproperlyConfigured):
            encrypt_bytes(b"test data")


# =============================================================================
# save_import_file — Sauvegarde + chiffrement sur disque
# =============================================================================


class TestSaveImportFile:
    """Tests de la fonction save_import_file."""

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_creates_encrypted_file(self, tmp_path):
        """Le fichier est créé avec extension .enc dans le bon sous-dossier."""
        from imports.storage import save_import_file

        # Fichier source temporaire
        src = tmp_path / "transactions.csv"
        src.write_bytes(b"date,amount\n2026-01-15,-50.00")

        storage_root = tmp_path / "storage"
        with override_settings(IMPORT_STORAGE_ROOT=storage_root):
            rel_path, is_encrypted = save_import_file(
                src=src,
                institution_slug="yuh",
                stored_filename="yuh_checking_20260101_20260131_10tx.csv",
                year=2026,
            )

        # Le fichier doit exister avec .enc
        dest = storage_root / rel_path
        assert dest.exists()
        assert dest.suffix == ".enc"
        assert is_encrypted is True

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_stored_content_is_not_plaintext(self, tmp_path):
        """Le fichier stocké ne contient pas les données en clair."""
        from imports.storage import save_import_file

        original_content = b"date,amount,description\n2026-01-15,-50.00,MIGROS"
        src = tmp_path / "transactions.csv"
        src.write_bytes(original_content)

        storage_root = tmp_path / "storage"
        with override_settings(IMPORT_STORAGE_ROOT=storage_root):
            rel_path, _ = save_import_file(
                src, "yuh", "yuh_check_20260101_20260131_1tx.csv", 2026
            )
            dest_content = (storage_root / rel_path).read_bytes()

        # Le contenu stocké ne doit pas contenir les données brutes
        assert original_content not in dest_content
        assert b"MIGROS" not in dest_content

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_decryptable_after_save(self, tmp_path):
        """Un fichier stocké peut être déchiffré et redonne les données originales."""
        from imports.storage import decrypt_bytes, save_import_file

        original_content = b"date,amount\n2026-01-15,-50.00"
        src = tmp_path / "transactions.csv"
        src.write_bytes(original_content)

        storage_root = tmp_path / "storage"
        with override_settings(IMPORT_STORAGE_ROOT=storage_root):
            rel_path, _ = save_import_file(
                src, "yuh", "yuh_check_20260101_20260131_1tx.csv", 2026
            )
            ciphertext = (storage_root / rel_path).read_bytes()

        assert decrypt_bytes(ciphertext) == original_content

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_creates_directory_structure(self, tmp_path):
        """Les sous-dossiers {bank}/{year}/ sont créés automatiquement."""
        from imports.storage import save_import_file

        src = tmp_path / "file.csv"
        src.write_bytes(b"data")

        storage_root = tmp_path / "new_storage"
        with override_settings(IMPORT_STORAGE_ROOT=storage_root):
            rel_path, _ = save_import_file(
                src, "ubs", "ubs_check_20260101_20260131_5tx.csv", 2026
            )

        dest = storage_root / rel_path
        assert dest.exists()
        assert (storage_root / "ubs" / "2026").is_dir()

    @override_settings(IMPORT_ENCRYPTION_KEY=TEST_FERNET_KEY)
    def test_returns_relative_path(self, tmp_path):
        """Le chemin retourné est relatif à IMPORT_STORAGE_ROOT (pas absolu)."""
        from imports.storage import save_import_file

        src = tmp_path / "file.csv"
        src.write_bytes(b"data")

        storage_root = tmp_path / "storage"
        with override_settings(IMPORT_STORAGE_ROOT=storage_root):
            rel_path, _ = save_import_file(
                src, "cic", "cic_multi_20260101_20260131_3tx.xlsx", 2026
            )

        # Un chemin relatif ne commence pas par /
        assert not str(rel_path).startswith("/")
        # Il commence par l'institution_slug
        assert str(rel_path).startswith("cic/")

    @override_settings(IMPORT_ENCRYPTION_KEY="")
    def test_missing_key_raises(self, tmp_path):
        """Clé absente → ImproperlyConfigured (ne stocke pas en clair silencieusement)."""
        from django.core.exceptions import ImproperlyConfigured

        from imports.storage import save_import_file

        src = tmp_path / "file.csv"
        src.write_bytes(b"data")

        with override_settings(IMPORT_STORAGE_ROOT=tmp_path):
            with pytest.raises(ImproperlyConfigured):
                save_import_file(src, "yuh", "yuh_check_nodate_nodate_0tx.csv", 2026)
