# Architecture — BricBudget

> Carte d'entrée pour humains **et agents** (Claude Code / Serena MCP).
> But : situer une responsabilité sans lire 10 fichiers à l'aveugle.
> Le détail privé (vocabulaire, IBAN, décisions) vit dans `.claude/project/` (gitignoré).

Stack : **Django** + **HTMX** + **Tailwind** + **PostgreSQL**. État UI en sessions Django.
Code applicatif sous `src/`. Outillage de navigation : voir [.claude/agent-codenav.md](.claude/agent-codenav.md).

---

## Apps Django (`src/`)

| App | Rôle | Modèles clés | Services |
|-----|------|--------------|----------|
| **transactions** | Cœur : transactions, catégorisation, budget mensuel, journal d'import | `Transaction`, `Category`, `SubCategory`, `CategorizationRule`, `ImportLog`, `BudgetTarget` | `import_service`, `internal_transfer`, `file_hash` |
| **accounts** | Comptes & institutions (bancaires + placements), soldes, FX | `Account`, `Institution`, `Card`, `CheckingAccount`, `SavingsAccount`, `LifeInsuranceDetails`, `PensionDetails`, `BalanceSnapshot`, `ExchangeRate` | — |
| **patrimoine** | Vue patrimoine par classe d'actifs : valorisation, bilan, historique de solde, données de graphes | (s'appuie sur `accounts`) | `valuation`, `bilan`, `balance_history`, `asset_classes`, `chart_data` |
| **budget** | Écran budget (vues package `budget/views/`) | `budget/models.py` | — |
| **imports** | Wizard d'import CSV (dry-run → confirm), pilote les connecteurs | — | (utilise `connectors/`) |
| **users** | Auth (`CustomUser`), profil | `CustomUser` (via `users.models`), `Profile`, `CustomUserManager` | — |
| **demo** | Données de démo / fixtures | — | — |

## Code transverse (`src/`, hors apps)

| Dossier | Rôle | Modules |
|---------|------|---------|
| **services/** | Services applicatifs partagés, **un module = un service** (pas de dossier par service) | `exchange_rates` (`to_chf` — porte unique de conversion), `logos`, `colors`, `palette` |
| **connectors/** | Parsers d'import par banque (`base.py` + un dossier par banque) | `cic/`, `ubs/`, `yuh/`, `resolver.py` |
| **config/** | Settings Django, urls racine, wsgi/asgi | — |

---

## Frontières de sécurité (SR-XX → `.claude/SECURITY_RULES.md`)

L'isolation multi-user passe par des **managers `for_user`** — jamais de `.objects` nu sur du
contenu utilisateur. Points d'entrée à connaître (audit `ast-grep` : voir `sgconfig.yml`) :

| `for_user` | Fichier |
|-----------|---------|
| `TransactionQuerySet.for_user` | `src/transactions/models.py:352` |
| `OwnedQuerySet` / `OwnedManager.for_user` | `src/transactions/managers.py` |
| `AccountQuerySet.for_user` | `src/accounts/models/account.py` |

Invariants : `Transaction.objects.for_user(request.user)`, précision monétaire `Decimal(str(x))`,
atomicité `transaction.atomic()`, jamais de `print()` (→ `logger`).

---

## Où chercher quoi (heuristiques agent)

- **Une vue / un endpoint** → `src/<app>/views.py` ou `src/<app>/views/` (package : `patrimoine`, `budget`).
- **Une règle métier réutilisable** → `src/<app>/services/` ou `src/services/` (transverse).
- **Un parser de banque** → `src/connectors/<banque>/`.
- **Une conversion de devise** → `services.exchange_rates.to_chf` (porte unique).
- **Un modèle** → `src/<app>/models.py` ou `src/<app>/models/` (package : `accounts`).
- **Le vocabulaire / module map détaillé (privé)** → `.claude/project/UBIQUITOUS_LANGUAGE.md`.
