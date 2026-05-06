"""
imports/storage.py — Stockage permanent + chiffrement des fichiers d'import bancaires.

Pourquoi chiffrer ?
    Les CSV/Excel bancaires contiennent des données financières personnelles :
    montants, IBAN, noms de marchands. Même sur un Mac local avec FileVault,
    on chiffre pour se protéger contre un backup non chiffré ou un accès
    non autorisé au système de fichiers (clé USB, Time Machine non encrypté).

Pourquoi Fernet ?
    Fernet (AES-128-CBC + HMAC-SHA256) est le standard de la bibliothèque
    `cryptography`. Il garantit :
        - Confidentialité  : AES-128-CBC (clé symétrique)
        - Intégrité        : HMAC-SHA256 (détecte toute altération du fichier)
        - Non-rejeu        : IV aléatoire à chaque chiffrement (même donnée → ciphertext différent)

    Une clé Fernet = 32 bytes aléatoires encodés en base64-urlsafe.
    Elle est stockée dans .env sous IMPORT_ENCRYPTION_KEY.

Clé OBLIGATOIRE :
    Si IMPORT_ENCRYPTION_KEY est absent du .env → ImproperlyConfigured au moment
    de l'appel. Le démarrage Django lui-même échoue si la variable est manquante
    (config() sans default lève UndefinedValueError).

Structure de stockage :
    IMPORT_STORAGE_ROOT / {bank_slug} / {year} / {stored_filename}.enc

    Exemple :
        assets/private/data/imports/yuh/2026/yuh_checking_20260101_20260430_b12345.67_42tx.csv.enc
        assets/private/data/imports/cic/2026/cic_multi_20260101_20260430_5tx.xlsx.enc

    Le chemin stocké en DB est RELATIF à IMPORT_STORAGE_ROOT pour rester
    portable entre machines (pas de chemin absolu /Users/manulabricole/...).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# =============================================================================
# Clé de chiffrement
# =============================================================================


def _get_key() -> bytes:
    """
    Retourne la clé Fernet depuis settings.IMPORT_ENCRYPTION_KEY.

    Lève ImproperlyConfigured si la clé est vide ou absente.
    Cette vérification est faite à l'appel (pas au démarrage Django) pour
    permettre aux tests d'utiliser @override_settings sans redémarrer.
    """
    key = getattr(settings, "IMPORT_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured(
            "IMPORT_ENCRYPTION_KEY est obligatoire pour les imports web. "
            'Générer : python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    # La clé est stockée en str dans .env → on encode en bytes pour Fernet
    return key.encode() if isinstance(key, str) else key


# =============================================================================
# Chiffrement / déchiffrement
# =============================================================================


def encrypt_bytes(data: bytes) -> bytes:
    """
    Chiffre des données brutes avec Fernet.

    L'appel importe Fernet ici (et non au niveau module) pour deux raisons :
        1. Évite l'import de `cryptography` si le module est importé mais la
           fonction jamais appelée (ex: tests CLI sans clé).
        2. Permet à @override_settings de fonctionner sans reload du module.
    """
    from cryptography.fernet import Fernet

    return Fernet(_get_key()).encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    """
    Déchiffre des données Fernet.

    Lève cryptography.fernet.InvalidToken si les données sont altérées
    ou si la clé est incorrecte — ne jamais ignorer cette exception en prod.
    """
    from cryptography.fernet import Fernet

    return Fernet(_get_key()).decrypt(data)


# =============================================================================
# Convention de nommage
# =============================================================================


def build_import_filename(
    bank_slug: str,
    account_names: list[str],
    date_min: date | None,
    date_max: date | None,
    balance: Decimal | None,
    n_transactions: int,
    original_ext: str,
) -> str:
    """
    Construit le nom de fichier canonique pour un fichier d'import.

    Convention :
        {bank}_{account}_{date_min}_{date_max}[_b{balance}]_{n}tx{ext}

    Paramètres :
        bank_slug      : slug de la banque ("yuh", "ubs", "cic")
        account_names  : liste de noms de comptes normalisés (snake_case)
                         Si plusieurs comptes (CIC multi-feuilles) → "multi"
        date_min       : date de la transaction la plus ancienne du fichier
        date_max       : date de la transaction la plus récente
        balance        : solde extrait du fichier (None si non disponible)
        n_transactions : nombre de transactions nouvellement créées en DB
        original_ext   : extension originale du fichier (".csv", ".xlsx")

    Exemples :
        yuh_checking_20260101_20260430_b12345.67_42tx.csv
        ubs_compte_courant_20260201_20260430_b45678.90_15tx.csv
        cic_multi_20260101_20260430_5tx.xlsx
        yuh_checking_nodate_nodate_0tx.csv  (quand toutes les tx sont des doublons)

    Pourquoi cette convention ?
        - Tri chronologique naturel (ls -la → ordre temporel)
        - Banque identifiable immédiatement sans ouvrir le fichier
        - Balance pour vérification rapide en cas de divergence comptable
        - n_transactions pour détecter les imports partiels ou les réimports
    """
    # Un seul compte → son nom normalisé. Plusieurs → "multi" (CIC multi-feuilles)
    account_part = account_names[0] if len(account_names) == 1 else "multi"

    # Fallback "nodate" si aucune transaction n'a été insérée (all skipped)
    date_min_str = date_min.strftime("%Y%m%d") if date_min else "nodate"
    date_max_str = date_max.strftime("%Y%m%d") if date_max else "nodate"

    # Balance optionnelle — certains connecteurs ne peuvent pas l'extraire
    balance_part = f"_b{balance:.2f}" if balance is not None else ""

    # Normaliser l'extension : ".csv" → "csv"
    ext = original_ext.lstrip(".")

    return f"{bank_slug}_{account_part}_{date_min_str}_{date_max_str}{balance_part}_{n_transactions}tx.{ext}"


# =============================================================================
# Sauvegarde permanente
# =============================================================================


def save_import_file(
    src: Path,
    bank_slug: str,
    stored_filename: str,
    year: int,
) -> tuple[Path, bool]:
    """
    Chiffre et copie un fichier d'import vers le stockage permanent.

    Structure de destination :
        IMPORT_STORAGE_ROOT / {bank_slug} / {year} / {stored_filename}.enc

    Le ".enc" est ajouté automatiquement pour distinguer les fichiers chiffrés
    des éventuels fichiers non chiffrés laissés par des imports CLI anciens.

    Returns :
        (relative_path, is_encrypted)
        relative_path : Path RELATIF à IMPORT_STORAGE_ROOT (ex: yuh/2026/yuh_...csv.enc)
        is_encrypted  : toujours True pour les imports web (clé obligatoire)

    Lève :
        ImproperlyConfigured  si IMPORT_ENCRYPTION_KEY est absent
        OSError               si le dossier de destination ne peut pas être créé
    """
    storage_root = Path(settings.IMPORT_STORAGE_ROOT)
    dest_dir = storage_root / bank_slug / str(year)

    # exist_ok=True : pas d'erreur si le dossier existe déjà
    # parents=True  : crée toute la hiérarchie (yuh/2026/) si nécessaire
    dest_dir.mkdir(parents=True, exist_ok=True)

    # On ajoute .enc pour signaler clairement que le fichier est chiffré
    dest_path = dest_dir / (stored_filename + ".enc")

    # Chiffrement Fernet → lève ImproperlyConfigured si clé absente
    data = src.read_bytes()
    dest_path.write_bytes(encrypt_bytes(data))

    # Chemin relatif à IMPORT_STORAGE_ROOT — portable entre machines
    relative_path = dest_path.relative_to(storage_root)
    return relative_path, True
