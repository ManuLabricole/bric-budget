# Système d'import CSV — BricBudget

> Dernière mise à jour : 2026-04-03

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
│  matches_file(path) → bool       ← détection de format             │
│  extract_iban(path) → str|None   ← identification du compte        │
│  extract_balance(path) → float   ← snapshot de solde              │
│  parse(path) → list[TransactionDict]                               │
│                                                                     │
│  Contrat commun : TransactionDict (connectors/base.py)             │
│  { date, time, amount, currency, description_raw,                  │
│    merchant_name, card_last_four, import_hash }                    │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ list[TransactionDict]
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│               MANAGEMENT COMMAND — dry run (Phase 1A)              │
│       transactions/management/commands/import_<bank>.py             │
│                                                                     │
│  1. matches_file()   → valide le format du fichier                 │
│  2. Détecte Account  → via IBAN (UBS) ou convention bank (Yuh)     │
│  3. Charge Cards     → dict {last_four: Card} pour matching        │
│  4. parse()          → liste des transactions parsées              │
│  5. Dédup            → compare import_hash vs Transaction DB       │
│  6. Rapport          → new / duplicate / cardholder               │
│                                                                     │
│  ⚠  DRY RUN — aucune écriture en DB à ce stade                    │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ (Phase 1B — à implémenter)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ÉCRITURE DB                                  │
│                                                                     │
│  Transaction.objects.bulk_create(new_txs)                          │
│  Card matching → Transaction.card = Card                           │
│  BalanceSnapshot.objects.update_or_create(...)                     │
│  ImportLog.objects.create(status, counts, file_hash)               │
│                                                                     │
│  Dédup finale : import_hash UNIQUE → IntegrityError = skip         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Détection du compte (Niveau 1)

Chaque connecteur identifie le compte bancaire associé au fichier.
Stratégie différente selon ce que le fichier expose :

| Connecteur | Identifiant dans le fichier | Stratégie de matching |
|---|---|---|
| **Yuh** | Aucun | Convention : seul compte `bank=yuh + type=checking` actif en DB. Erreur si 0 ou 2+. |
| **UBS** | IBAN (ligne 2) | `extract_iban()` → normalise (sans espaces) → `CheckingAccount.iban` |
| **CIC** | RIB (en-tête Excel) | À implémenter — probablement IBAN par feuille |

---

## Détection de la carte (Niveau 2)

Pour chaque transaction, on identifie quelle carte (et donc quel porteur) l'a générée.

```
Fichier CSV  →  card_last_four  →  dict {last_four: Card}  →  Card.user
    "**** 1150"       "1150"         (chargé en 1 query)       Emmanuel
    "**** 8803"       "8803"                                    Carys
    (virement)         None                                     (pas de carte)
    (inconnue)       "9999"         → [? *9999]                 non enregistrée
```

Le dict est construit **une seule fois** avant la boucle de parsing, pas une query par transaction.

---

## Modèles DB impliqués

```
Bank ──< Account ──< Transaction >── Category
              │                  └── SubCategory
              │                  └── Card (à lier en Phase 1B)
              ├──< CheckingAccount ──< Card >── User
              ├──< SavingsAccount
              └──< BalanceSnapshot

ImportLog >── Account
ImportLog >── User  (imported_by)
```

---

## Format normalisé — TransactionDict

Tous les connecteurs produisent ce format identique, défini dans `connectors/base.py` :

```python
class TransactionDict(TypedDict):
    date:            str        # ISO 8601 : "2026-03-17"
    time:            str | None # "HH:MM:SS" si dispo (UBS oui, Yuh non)
    amount:          float      # négatif = débit, positif = crédit
    currency:        str        # ISO 4217 : "CHF", "EUR", "GBP"
    description_raw: str        # texte brut de la banque — jamais modifié
    merchant_name:   str        # nom nettoyé, pré-rempli pour l'UI
    card_last_four:  str | None # "1150" pour paiement carte, None sinon
    import_hash:     str        # SHA1 des champs clés — déduplication
```

---

## Déduplication

L'`import_hash` est un SHA1 calculé sur les champs qui identifient uniquement une transaction.
Il est différent par connecteur :

| Connecteur | Champs hashés |
|---|---|
| **Yuh** | `date \| activity_type \| amount \| description_raw` |
| **UBS** | `date \| time \| amount \| description1` |

Le champ `Transaction.import_hash` est `unique=True` en DB — filet de sécurité final si le rapport dry-run était bypassed.

---

## Filtrage des lignes

| Connecteur | Approche | Lignes exclues |
|---|---|---|
| **Yuh** | **Blacklist** (`SKIPPED_ACTIVITY_TYPES`) | `REWARD_RECEIVED` uniquement — cashback sans valeur CHF |
| **UBS** | Tout importé | Aucune ligne filtrée — UBS n'inclut pas les ordres FX dans le fichier transactionnel |

Le choix de la blacklist pour Yuh est intentionnel : tout nouveau type d'activité est importé par défaut, pas ignoré silencieusement.

---

## État d'avancement

| Connecteur | Parser | Commande | Détection compte | Détection carte | Écriture DB |
|---|---|---|---|---|---|
| **Yuh** | ✅ | ✅ `make import-yuh` | ✅ convention | ✅ last_four | ⏳ Phase 1B |
| **UBS** | ✅ | ✅ `make import-ubs` | ✅ IBAN | ❌ format inconnu | ⏳ Phase 1B |
| **CIC** | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## Commandes disponibles

```bash
make import-yuh FILE=path/to/Activités_2026_03_17.csv
make import-ubs FILE=path/to/ubs_export.csv
```

Les deux commandes sont en **dry run** — elles affichent un rapport complet mais n'écrivent rien en DB.
