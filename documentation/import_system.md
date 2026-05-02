# Système d'import CSV — BricBudget

> Dernière mise à jour : 2026-04-29

---

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FICHIER SOURCE                              │
│   Yuh CSV  ·  UBS CSV  ·  CIC Excel  ·  (futur: Finpension...)     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       CONNECTOR LAYER                               │
│                  connectors/<bank>/parser.py                        │
│                                                                     │
│  matches_file(path) → bool          ← détection de format          │
│  extract_account_identifier(path)   ← identification du compte     │
│  extract_balance(path) → float|None ← snapshot de solde            │
│  parse(path) → list[TransactionDict]                                │
│                                                                     │
│  Contrat commun : TransactionDict (connectors/base.py)             │
│  { date, time, amount, currency, description_raw,                  │
│    merchant_name, card_last_four, import_hash }                    │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    RESOLVER — connectors/resolver.py                │
│                                                                     │
│  detect_connector(path) → BaseConnector|None                       │
│      Itère CONNECTORS jusqu'au premier matches_file() = True        │
│                                                                     │
│  resolve_accounts(connector, path) → list[AccountMatch]            │
│      Yuh  → convention (1 compte Yuh checking actif en DB)         │
│      UBS  → IBAN extrait → Account.contract_number                 │
│      CIC  → RIB par feuille → Account.contract_number              │
│      → toujours une liste, même pour Yuh (1 élément)               │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ list[AccountMatch]
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│               CALLER — Management command ou Vue Django             │
│   transactions/management/commands/import_<bank>.py                │
│   imports/views.py (Phase 2F)                                       │
│                                                                     │
│  1. detect_connector()    → valide le format                        │
│  2. resolve_accounts()    → trouve le(s) compte(s) en DB           │
│  3. connector.parse()     → liste de TransactionDict                │
│  4. ImportService.run()   → tout le reste (voir ci-dessous)         │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  ImportService — transactions/services.py           │
│                                                                     │
│  1. Déduplique les lignes (import_hash SHA256 unique)               │
│  2. Résout les cartes (last_four → Card)                            │
│  3. Applique les règles de catégorisation                           │
│  4. Si dry_run=True → STOP, retourne les compteurs                  │
│  5. Écrit les Transaction en bulk                                   │
│  6. Crée/met à jour BalanceSnapshot (extracted + computed)          │
│  7. Crée ImportLog (résumé de la session)                           │
│                                                                     │
│  → retourne ImportResult(count_created, count_skipped, count_errors)│
└─────────────────────────────────────────────────────────────────────┘
```

---

## Resolver — `connectors/resolver.py`

Point d'entrée unique pour toute la logique de détection et de résolution.
**Les commandes de management et la vue Phase 2F utilisent toutes ce module.**

### `detect_connector(filepath)` → `BaseConnector | None`

Retourne le premier connecteur dont `matches_file()` retourne `True`.
`None` = format non reconnu.

### `AccountMatch` — dataclass de retour

```python
@dataclass
class AccountMatch:
    account: Account        # objet Account en DB
    sheet_name: str | None  # None pour Yuh/UBS, nom de feuille pour CIC
    parse_kwargs: dict      # {} pour Yuh/UBS, {"sheet_name": "..."} pour CIC
```

### `resolve_accounts(connector, filepath)` → `list[AccountMatch]`

Toujours une liste — le caller peut itérer uniformément sans cas particulier.

| Connecteur | Logique de matching |
|------------|---------------------|
| **Yuh** | Convention : 1 seul `Account(bank__slug="yuh", account_type="checking", is_active=True)` |
| **UBS** | `extract_account_identifier()` → IBAN normalisé → `CheckingAccount.iban` |
| **CIC** | `get_account_sheets()` → RIB par feuille → `Account.contract_number` |

Lève `AccountNotFound` (exception custom dans `resolver.py`) si le compte est absent.
`AccountNotFound` porte : `contract_number`, `contract_number_raw`, `bank_slug`, `sheet_name`.
La vue catch cette exception et affiche le fragment `_steps_create_account.html` pour créer le compte inline.

---

## Banques supportées — `accounts/banks_config.py`

Source de vérité pour les banques incorporées dans l'app.
Un seul fichier Python, pas de fixture — idempotent et versionné.

```python
KNOWN_BANKS = {
    "yuh":        { "name": "Yuh",        "currency": "CHF", "bic": "YUHHCHZZ",    "country": "CH" },
    "ubs":        { "name": "UBS",        "currency": "CHF", "bic": "UBSWCHZH80A", "country": "CH" },
    "cic":        { "name": "CIC",        "currency": "EUR", "bic": "CMCIFRPP",    "country": "FR" },
    "boursorama": { "name": "Boursorama", "currency": "EUR", "bic": "BOUSFRPPXXX", "country": "FR" },
    "finpension": { "name": "Finpension", "currency": "CHF", "bic": "",            "country": "CH" },
}
```

Commande de seed (idempotente) :
```bash
python manage.py seed_banks   # crée ou met à jour les Bank en DB
```

### Ajouter une nouvelle banque
1. Ajouter une entrée dans `KNOWN_BANKS` (slug = clé)
2. Déposer l'icône dans `static/icons/banks/miniature/<slug>.png`
3. `python manage.py seed_banks`
4. Créer `connectors/<bank>/parser.py` si un export existe
5. Ajouter dans `CONNECTORS` + `resolve_accounts()` dans `resolver.py`

---

## Création de compte inline (UI Import)

Quand `resolve_accounts()` lève `AccountNotFound`, la vue affiche `_steps_create_account.html` :
- Banque pré-sélectionnée (logo + nom depuis `banks_config`)
- IBAN pré-rempli si UBS (extrait du fichier), vide sinon
- BIC pré-rempli depuis `banks_config`
- Nom, type, devise à compléter
- `contract_number` passé en champ caché (RIB pour CIC, IBAN pour UBS)

Après soumission → vue `import_create_account` :
1. Crée `Account` + `CheckingAccount` (ou `SavingsAccount`)
2. Relance le dry-run depuis le fichier toujours en session
3. Retourne `_steps_result.html` → flux normal

Si CIC a plusieurs feuilles inconnues, `AccountNotFound` est relancée pour la suivante.

### Compte incomplet (`is_complete = False`)
- `CheckingAccount.is_complete` → `bool(iban and bic)` — alerte si BIC manquant
- `SavingsAccount.is_complete` → `interest_rate > 0` — alerte si taux non renseigné
- Le warning sera affiché dans **Patrimoine → Comptes bancaires** (Phase 3A)

---

## Dual balance — `extracted` vs `computed`

Chaque import crée/met à jour un `BalanceSnapshot` avec deux valeurs :

```
Import
  │
  ├── balance (extracted)
  │     Yuh : regex sur le nom de fichier — fragile (URL-encoding macOS peut casser)
  │     UBS : metadata ligne 6 — fiable
  │     CIC : footer de chaque feuille — fiable
  │     → None si le connecteur ne peut pas extraire
  │
  └── computed_balance
        = BalanceSnapshot.précédent (balance ?? computed_balance)
          + sum(amount pour chaque nouvelle transaction)
        → None sur le 1er import (pas de base de calcul)

.authoritative_balance = balance si présent, sinon computed_balance
.drift                 = balance - computed_balance (None si l'un manque)
```

Si `|drift| > 0.01` → warning dans les logs Django (`transactions.services`).
Causes possibles : transaction manquante, arrondi de la banque, export partiel.

---

## Déduplication

Deux niveaux :

| Niveau | Champ | Portée |
|--------|-------|--------|
| **Ligne** | `Transaction.import_hash` (SHA256) | Évite les doublons par transaction |
| **Fichier** | `ImportLog.file_hash` (SHA1) | Évite de ré-importer le même fichier |

L'`import_hash` est calculé sur les champs qui identifient une transaction de façon unique :

| Connecteur | Champs hashés |
|------------|---------------|
| **Yuh** | `date \| activity_type \| amount \| description_raw` |
| **UBS** | `date \| time \| amount \| description1` |
| **CIC** | `date \| amount \| description \| balance` |

Pour CIC multi-feuilles, le `file_hash` de l'`ImportLog` est `sha1(file_hash:sheet_name)` pour rester unique par (fichier, feuille).

---

## Filtrage des lignes

| Connecteur | Approche | Lignes exclues |
|------------|----------|----------------|
| **Yuh** | Blacklist (`SKIPPED_ACTIVITY_TYPES`) | `REWARD_RECEIVED` uniquement |
| **UBS** | Tout importé | Aucune — UBS n'inclut pas les ordres FX |
| **CIC** | Tout importé | Aucune |

Le choix de la blacklist pour Yuh est intentionnel : tout nouveau type d'activité est importé par défaut, pas ignoré silencieusement.

---

## Détection de carte (Niveau 2)

Pour chaque transaction, on identifie quelle carte (et donc quel porteur) l'a générée.

```
Fichier CSV  →  card_last_four  →  dict {last_four: Card}  →  Card.user
    "**** 1150"       "1150"         (chargé en 1 query)       Emmanuel
    "**** 8803"       "8803"                                    Carys
    (virement)         None                                     (pas de carte)
    (inconnue)       "9999"         → [? *9999]                 non enregistrée
```

---

## Guides d'extension

### Ajouter une nouvelle banque

1. Créer `Bank` en DB (admin ou seed) — `name`, `slug`, `country`, `default_currency`
2. Créer `connectors/<slug>/parser.py` :
   - `matches_file(path) → bool` — inspecte extension, encodage, colonnes
   - `parse(path) → list[TransactionDict]` — lit et normalise les lignes
   - `extract_balance(path) → float | None` — optionnel
   - `extract_account_identifier(path) → str | None` — optionnel (IBAN/RIB)
3. Ajouter le connecteur dans `CONNECTORS` dans `connectors/resolver.py` (une ligne)
4. Ajouter un `elif isinstance(connector, NouvelleConnector):` dans `resolve_accounts()`

### Ajouter un nouveau compte (banque existante)

1. Créer `Account` en DB — `bank`, `name`, `account_type`, `currency`, `is_active=True`
2. Créer la spécialisation :
   - `CheckingAccount` (IBAN + BIC) pour comptes courants
   - `SavingsAccount` (taux d'intérêt) pour livrets
3. Renseigner `Account.contract_number` :
   - UBS → IBAN sans espaces : `"CH93XXXXXXXXXXXXXXXXXXX"`
   - CIC → RIB sans espaces : `"10096XXXXXXXXXXXXXXXXXXX"`
   - Yuh → laisser vide (convention : exactement 1 compte Yuh checking actif)

### Ajouter une nouvelle carte

1. Créer `Card` en DB — `checking_account`, `user`, `last_four`, `card_type`, `is_active=True`
2. C'est tout — le connecteur lit `card_last_four` dans chaque ligne et le service fait le matching automatiquement.

---

## Format normalisé — `TransactionDict`

Tous les connecteurs produisent ce format identique, défini dans `connectors/base.py` :

```python
class TransactionDict(TypedDict):
    date:            str        # ISO 8601 : "2026-03-17"
    time:            str | None # "HH:MM:SS" si dispo (UBS oui, Yuh/CIC non)
    amount:          float      # négatif = débit, positif = crédit
    currency:        str        # ISO 4217 : "CHF", "EUR", "GBP"
    description_raw: str        # texte brut de la banque — jamais modifié
    merchant_name:   str        # nom nettoyé, pré-rempli pour l'UI
    card_last_four:  str | None # "1150" pour paiement carte, None sinon
    import_hash:     str        # SHA256 des champs clés — déduplication
```

---

## Modèles DB impliqués

```
Bank ──< Account ──< Transaction >── Category
              │                  └── SubCategory
              │                  └── Card
              ├──< CheckingAccount ──< Card >── User
              ├──< SavingsAccount
              └──< BalanceSnapshot (balance + computed_balance)

ImportLog >── Account
ImportLog >── User  (imported_by)
```

---

## État d'avancement

| Connecteur | Parser | Commande | Détection compte | Détection carte | Écriture DB |
|------------|--------|----------|-----------------|-----------------|-------------|
| **Yuh** | ✅ | ✅ `make import-yuh` | ✅ convention slug | ✅ last_four | ✅ |
| **UBS** | ✅ | ✅ `make import-ubs` | ✅ IBAN ligne 2 | ❌ format inconnu | ✅ |
| **CIC** | ✅ | ✅ `make import-cic` | ✅ RIB par feuille | ❌ non applicable | ✅ |

---

## Commandes disponibles

```bash
# Import d'un fichier spécifique
make import-yuh FILE=assets/private/data/raw/export.csv
make import-ubs FILE=assets/private/data/raw/export.csv
make import-cic FILE=assets/private/data/raw/export.xlsx

# Import de tous les fichiers du dossier raw
make import-all           # dry-run
make import-all COMMIT=1  # écriture en DB

# Avec le resolver (depuis le shell Python ou une vue)
from connectors.resolver import detect_connector, resolve_accounts
connector = detect_connector(Path("export.csv"))
matches = resolve_accounts(connector, Path("export.csv"))
```
