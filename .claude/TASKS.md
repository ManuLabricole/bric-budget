# TASKS — BricBudget
> Rythme : ~3h le samedi matin
> Mis à jour : 2026-05-12 (session 26 — Phase 2G T3 livré : catégories CRUD + panel gestion + tests)
> Détail opérationnel → GitHub Issues / Milestones

---

## ✅ Fait — Phase 0 : Initialisation + Planification (2026-03-29)

- [x] Analyse CSV Yuh + Excel CIC (format, colonnes, encodage)
- [x] Décision stack : Django + HTMX + Tailwind + PostgreSQL
- [x] 17 catégories + sous-catégories définies
- [x] Schéma DB v2 complet (`documentation/schema_db_v2.mermaid`)
- [x] Project Charter (`documentation/PROJECT_CHARTER.md`)
- [x] Structure `.claude/` avec HELLO protocol
- [x] CHANGELOG.md créé
- [x] Décisions DB finalisées : Bank, Account, CompteCourant, Card, BalanceSnapshot
- [x] git init + .gitignore + premier commit
- [x] Repo GitHub ManuLabricole/bric-budget connecté
- [x] Branches : main → development → feature/phase-0-scaffold
- [x] GitHub Project Board (Kanban) + Milestones + Labels
- [x] Poetry initialisé (Python 3.13, Django 6, psycopg2, decouple, ruff)
- [x] Scaffold Django : django-admin startproject config src/
- [x] docker-compose.yml : PostgreSQL 16 (port 5433)
- [x] .env.example + .env (python-decouple)
- [x] settings.py : PostgreSQL, Europe/Zurich, STATICFILES
- [x] make migrate → DB PostgreSQL → Django welcome page ✅
- [x] Makefile : make up/down/run/migrate/makemigrations/shell/logs/status/backup/restore
- [x] Deep dive Finary screenshots → plan produit complet
- [x] Challenge architecture → nouveaux champs modèles identifiés

---

## 📅 Phase 0A — Modèles & Migrations (Samedi 2026-04-05)
> Objectif : `make migrate` sans erreur. Tous les modèles en place.

### App `users/` ✅ (codé le 2026-03-30)
- [x] `CustomUser(AbstractUser)` — email login, username removed
- [x] `Profile(OneToOne CustomUser)` — language, display_currency

### App `accounts/` ✅ (2026-04-02)
- [x] `Bank` — name, slug, country, default_currency, is_active
- [x] `Bank.icon_slug` — identifiant icône banque (`static/icons/banks/<icon_slug>.svg`)
- [x] `Account` — bank, name, account_type, currency, is_active (`slug` supprimé — connecteurs utilisent le nom/banque)
- [x] `CheckingAccount(OneToOne Account)` — iban, bic
- [x] `SavingsAccount(OneToOne Account)` — interest_rate, account_reference — **ajouté 2026-04-02**
- [x] `BalanceSnapshot` — account, date, balance, currency, balance_chf, source
- [x] `Card(FK CheckingAccount, FK User)` — last_four, card_type (debit/credit), is_active — Phase 6: extra card details
- [x] `ExchangeRate` — date, from_currency, to_currency, rate

### App `transactions/`
- [x] `Category` — name, slug, icon, colour_hex, order, is_system, is_active
- [x] `SubCategory` — category, name, slug, icon, default_nature, is_active
- [x] `Transaction` — account, card, category, subcategory, nature, date, amount, currency, amount_chf, description_raw, merchant_name, note, categorization_source, categorization_rule, is_reconciled, is_ignored, is_recurring, is_internal_transfer, paired_transaction, import_hash
- [x] `CategorizationRule` — keyword, category, subcategory, target_field, priority, is_active
- [x] `ImportLog` — account, imported_by, filename, file_hash, imported_at, status, count_created, count_skipped, count_errors, error_detail
- [x] `BudgetTarget` — category (`OneToOneField`), amount (CHF) — *refactorisé 2026-04-23 : `period` supprimé, objectif mensuel global par catégorie*
- ~~`BudgetResult`~~ — **supprimé** : calculé live via `Transaction.aggregate(Sum('amount_chf'))`

### Package `connectors/` (Python pur, pas une app Django)
- [x] `connectors/base.py` — `BaseConnector` + `TransactionDict` TypedDict
- [x] `connectors/yuh/parser.py` — `YuhConnector` stub (implémentation Phase 1A)

### Infra
- [x] `make migrate` → toutes les migrations appliquées sans erreur
- [x] pre-commit hooks : ruff + djlint + commitizen

---

## ✅ Phase 0B — Auth + Admin + Seed (2026-04-01 → 2026-04-02)
> Objectif : `make up` → Django admin accessible → données de base présentes

- [x] Auth Django : login/logout (`/login/`, `/logout/`), `LOGIN_URL`, redirects
- [x] Template `registration/login.html` — dark custom
- [x] Admin `accounts/` : Bank, Account, CheckingAccount, SavingsAccount, Card, BalanceSnapshot, ExchangeRate
- [x] Admin `transactions/` : Category, SubCategory, CategorizationRule, Transaction, ImportLog, BudgetTarget
- [x] **Seed données initiales** — `seed_initial` + `reset_seed` :
  - 17 catégories + sous-catégories (depuis `categories.json`)
  - Banks : Yuh (CHF) · UBS (CHF) · CIC (EUR) · Boursorama (EUR)
  - Accounts : Yuh C/C · UBS C/C · UBS Épargne · CIC C/C · CIC Livret A · Boursorama C/C · Boursorama Épargne
  - Cards : Emmanuel/Yuh · Emmanuel/UBS · Carys/UBS · Emmanuel/CIC
  - `update_or_create` → idempotent + sync si valeurs changées
  - `make seed` / `make reset-seed`
  - Commandes dans `config/management/commands/` (cross-app → pas dans transactions/ ni accounts/)
- [x] Icônes banques dans `static/icons/banks/miniature/` (yuh, ubs, cic — Boursorama manquant)
- [x] Icônes banques SVG dans `static/icons/banks/svg/` — SVG `currentColor`, rendu propre dark theme (2026-04-17)
- [x] Architecture types de comptes clarifiée : Transactionnels (Checking/Savings) vs Positionnels (Phase 5+)

---

## ✅ Phase 1A — Connecteurs + Import dry-run (2026-04-03)
> Objectif : parsers CSV opérationnels, rapport d'import complet avant écriture DB

- [x] `connectors/base.py` : `BaseConnector` + `TransactionDict` TypedDict (date, time, amount, currency, description_raw, merchant_name, card_last_four, import_hash)
- [x] `Transaction.time` : champ TimeField ajouté (UBS a l'heure, Yuh/CIC non)
- [x] `Account.AccountType.CURRENT` → renommé `CHECKING` (cohérence avec `CheckingAccount`) + migration de données
- [x] `connectors/yuh/parser.py` : `YuhConnector` complet
  - Blacklist `SKIPPED_ACTIVITY_TYPES = {REWARD_RECEIVED}` — tout le reste importé
  - Extraction balance depuis nom de fichier
  - Détection compte : convention bank=yuh + type=checking
  - Détection carte : `card_last_four` → `Card` DB
- [x] `connectors/ubs/parser.py` : `UBSConnector` complet
  - Extraction IBAN depuis ligne 2
  - Extraction balance depuis bloc metadata (Solde final)
  - Champ `time` rempli pour les paiements carte
- [x] `transactions/management/commands/import_yuh.py` : rapport dry-run complet
- [x] `transactions/management/commands/import_ubs.py` : rapport dry-run complet
- [x] Seed mis à jour : vrais `last_four` Yuh (1150 Emmanuel, 8803 Carys), Carys ajoutée sur Yuh
- [x] `make import-yuh` / `make import-ubs` dans le Makefile
- [x] `documentation/import_system.md` : schéma complet du système d'import

**Résultats validés**
- Yuh : 226 transactions parsées, 168 REWARD_RECEIVED skippées, cartes matchées
- UBS : 24 transactions parsées, 0 skippées, IBAN extrait correctement

**Livré (complété 2026-04-03 + 2026-04-06)**
- [x] `connectors/cic/parser.py` : Excel multi-feuilles, RIB par feuille
- [x] `connectors/ubs/parser.py` : complet
- [x] `transactions/services.py` : `ImportService` + `ImportResult` + `compute_file_hash`
- [x] `import_yuh.py` / `import_ubs.py` / `import_cic.py` refactorisés (mince, appellent le service)

**Refacto connecteurs — ✅ livré 2026-04-06**
- [x] `connectors/base.py` : `extract_account_identifier(filepath) → str | None` (défaut None)
- [x] `connectors/ubs/parser.py` : `extract_account_identifier()` retourne IBAN normalisé (sans espaces)
- [x] `seed_initial.py` + `reset_seed.py` : IBANs/RIBs lus depuis `.env` via `config()` — jamais hardcodés
- [x] `import_ubs.py` : utilise `extract_account_identifier()` + lookup `Account.contract_number`
- [x] pre-commit hook `no-hardcoded-bank-ids` : bloque IBAN CH/FR + RIB 20-22 chiffres dans les `.py`
- [x] `feature/phase-1a-import-yuh` mergé → `development` → `main` → pushé GitHub

---

## ✅ Phase 1B — Infrastructure UI + Budget connecté DB (2026-04-07)
> Branche : `feature/phase-1b-transactions-ui`

### Infrastructure UI ✅ (2026-04-06 → 2026-04-07)

- [x] Tailwind CSS CDN Play + Design System Finary (tokens dans `base.html`)
- [x] `.bb-background` — 3 couches gradient
- [x] `base.html` — `font-size: 13px`, `{% endblock %}` sans nom (Django 6)
- [x] `base_app.html` — topbar fixe globale + layout 2 panels (`panel_left` flex-[2] / `panel_right` flex-[1])
- [x] `sidebar.html` — lien Budget câblé, active via `app_name`
- [x] `config/urls.py` — include `transactions.urls` → `/budget/`
- [x] `transactions/urls.py` — 3 routes : list / period / tab

### Budget prototype + DB ✅ (2026-04-07)

- [x] `transactions/budget.html` — page Budget inspirée Finary :
  - Nav période : pill ← date ▾ →, boutons circulaires 1M/3M/1A, pill Personnalisé
  - Header Cashflow + contrôles (toggle, dropdowns rounded-full, copy/expand)
  - Placeholder Sankey `h-44`
  - KPI tabs (icônes + gold actif + underline `border-b -mb-px`)
  - Liste catégories (cercles colorés, montants, chevron hover gold)
  - Séparateurs `border-edge` entre sections
- [x] Panel droit Distribution : SVG donut + légende — `flex-[1]`, fit-content
- [x] `transaction_list()` branchée sur la DB : aggregation Sum, KPIs, donut math en Python
- [x] Navigation période : prev/next (session) + clamping futur (`can_go_next`)
- [x] Sélecteurs 1M/3M/1A fonctionnels via session + `budget_set_period()`
- [x] Onglets Entrées/Sorties fonctionnels via `budget_set_tab()` + session
- [x] `transactions/templatetags/budget_filters.py` — `|chf` (0 déc.) + `|chf_dec` (2 déc.), séparateur espace U+202F, virgule décimale
- [x] Disponible : vert (`text-income`) si ≥ 0, rouge (`text-expense`) si négatif
- [x] Onglet Récurrentes désactivé — badge SOON glassmorphism
- [x] Bouton Personnalisé désactivé — badge SOON glassmorphism
- [x] `components/badges/soon.html` — composant réutilisable (gold + bleu navy + backdrop-blur + gradient border)
- [x] `dev_randomize_categories` management command (coverage guarantee) + `make dev-randomize`
- [x] État vide catégories — inline dans `budget.html` (pas de composant séparé — YAGNI)

### ~~Composants data~~ — YAGNI (décidé 2026-04-06)

- ~~`components/data/amount.html` + template tag~~ — `{% if amount > 0 %}` inline suffit
- ~~`components/data/category_badge.html` + template tag~~ — idem
- ~~`transactions/templatetags/budget_tags.py`~~ — supprimé du plan

### Right Panel "Tout voir" ✅ (2026-04-07)

- [x] `transactions/_panel_tx_list.html` — fragment HTMX, liste 5 colonnes style Finary
- [x] `budget_panel_transactions()` — vue HTMX, résolution icônes, filtre `q` live search
- [x] `budget_panel_navigate(request, action)` — navigation période dans le panel (session + fragment)
- [x] URLs `panel/transactions/` + `panel/transactions/<action>/`
- [x] `components/period/period_nav.html` — composant navigation période (href + HTMX)
- [x] `components/search/search_bar.html` — recherche live HTMX + bouton × clear
- [x] `components/banks/account_badge.html` — badge banque réutilisable
- [x] `Bank.domain` + migration `0006_add_bank_domain.py`
- [x] `update_bank_logos` command + `make update-bank-logos`
- [x] Right panel : flottant + transparent + blur (`backdrop-blur-xl bg-surface-2/70`)

### Reste Phase 1B (non bloquant)

- [x] Icônes catégories : `Category.icon` → `static/icons/categories/<name>.svg` — ✅ livré Phase 1C (2026-04-14)
- [ ] `components/ui/spinner.html` — loader HTMX (utile en Phase 1C seulement)
- ~~`merchant_name` en uppercase à l'import~~ — **YAGNI** : `display_name` remplace `merchant_name` dans toute l'UI (session 23)

---

## 📅 Phase 1C — HTMX Inline Edit (Samedi 2026-05-03)
> Objectif : toutes les actions sur une transaction sans rechargement de page
> Branche : `feature/phase-1c-htmx-edit`

### ✅ Déjà livré (2026-04-14)
- [x] **Ignorer** une transaction (toggle HTMX, `hx-swap="outerHTML"`, grisé + barré)
- [x] **Catégorisation inline** : clic ligne → picker catégorie HTMX → sous-catégories → POST → toast
- [x] CSRF global `hx-headers` sur `<body>` (`base.html`)
- [x] `_panel_tx_row.html` — fragment ligne transaction (outerHTML swap)
- [x] `_panel_category_picker.html` — picker accordéon + "Règle intelligente" SOON + bouton doré "Créer catégorie"
- [x] `_cat_picker_row.html` — ligne catégorie avec sous-cats formulaires HTMX
- [x] Toast "Catégorie modifiée" via `HX-Trigger` header + JS `CustomEvent`
- [x] Right panel : titre dynamique par fragment (suppression titre hardcodé du shell)

### Catégories & Icônes ✅ (2026-04-14)
> Bibliothèque icônes : **Tabler Icons** (MIT) — `static/icons/categories/<slug>.svg`
> Workflow : décision icône → téléchargement SVG → `categories.json` mis à jour → re-seed

- [x] **Migration** : `is_system` ajouté sur `SubCategory` (migration `0003_subcategory_is_system.py`)
- [x] **JSON** : `is_system` ajouté sur les 122 sous-catégories dans `categories.json`
- [x] **JSON** : `icon` mis à jour sur toutes les catégories et sous-catégories (Tabler Icons slugs)
- [x] **seed_initial** : lit et écrit `is_system` sur SubCategory à l'import
- [x] **Télécharger SVGs** dans `static/icons/categories/` — 114 icônes Tabler MIT
- [x] **Première passe icônes** — corrections (rosette, tag, home, download, burger, heartbeat, tools-kitchen, lock-square, dental...)
- [x] **Icônes dans budget.html** — cercles colorés `rounded-full` + SVG `brightness-0 invert` dans la liste catégories
- [x] **Icônes dans `_panel_tx_row.html`** — icône catégorie 44px dans chaque ligne transaction
- [x] **Picker redesigné** — hiérarchie 3 niveaux : header couleur pleine / Principale cercle plein icône blanche / sous-cats cercle 40% icône blanche (2026-04-15 : fix couleurs Principale)
- [x] **`outline-none`** sur `<details>` + `<summary>` — suppression ring bleu natif navigateur
- [ ] **Deuxième passe icônes** — déplacé en Phase 2A (affinage visuel après utilisation réelle)
- [x] **Badge "perso"** — afficher badge sur les sous-catégories `is_system=False` dans le picker

### Reste Phase 1C

#### Panneau "Détails de la transaction" ✅ (2026-04-17)
> Flux : clic tx dans liste → panneau détail → clic catégorie → picker
- [x] **Vue + URL** `budget_panel_tx_detail(request)` — GET `?tx_id=X` → retourne `_panel_tx_detail.html`
- [x] **Template** `_panel_tx_detail.html` — nom tx + montant / catégorie cliquable → picker / Compte · Montant · Date / badge "Règle intelligente appliquée" / 2 toggles HTMX
- [x] **Toggle "Pointer la transaction"** — `budget_toggle_reconcile()` POST, détecte `source` (list → row, detail → panneau)
- [x] **Toggle "Inclure dans l'analyse budgétaire"** — `budget_toggle_ignore()` étendu avec `source=detail`
- [x] **Rewire clic `_panel_tx_row.html`** — `hx-get` → `panel_tx_detail`
- [x] **Badge vert is_reconciled** dans `_panel_tx_row.html` — cercle `bg-income` + checkmark SVG
- [x] **Pointer depuis la liste** — bouton dans la row, toggle direct sans passer par le détail
- [x] **Admin `CategorizationRule`** — validation `clean()` + filtrage `formfield_for_foreignkey` (subcategory filtrée par category)

#### Autres actions Phase 1C
- [x] **Badge "perso"** — afficher badge sur les sous-catégories `is_system=False` dans le picker ✅ 2026-04-17
- [ ] **Déclarer virement interne** : sélectionner 2 transactions → les lier (`paired_transaction`) — *reporté : on_delete ignore() suffit pour l'instant*
- [x] **Wizard règle de catégorisation** — création depuis l'UI, preview "X transactions impactées", bulk apply ✅ 2026-04-17
  - [x] Toast "Catégorie modifiée" + CTA "Créer une règle" (bouton activé + `hx-get` dynamique via JS)
  - [x] Panel chips tokens cliquables depuis `description_raw` (split `|`, filtre bruit banque)
  - [x] Picker catégorie avec icônes dans le wizard (même rendu que le picker classique)
  - [x] Étape preview : count transactions impactées SANS modifier + bouton Valider/Retour
  - [x] Confirmation : `CategorizationRule` créée + bulk apply (exclut `categorization_source=MANUAL`)
  - Badge "RÈGLE INTELLIGENTE APPLIQUÉE" dans `_panel_tx_detail.html` (déjà en place, branché sur `categorization_source`)
- [x] **Taux de change** — frankfurter.app → `ExchangeRate` → `amount_chf` calculé à l'import pour les comptes non-CHF (CIC EUR, Carys GBP) ✅ livré Phase 2A branch (2026-04-18)

---

## ✅ Tests critiques — livrés Phase 2A (2026-04-18)
> 88 tests, 3.07s — pytest + pytest-django
> Branche : `feature/phase-2a-budget-kpis`

- [x] **Setup pytest** — `pyproject.toml [tool.pytest.ini_options]` + conftest.py + pytest + pytest-django (Poetry)
- [x] **Tests connecteurs parsers** (`src/tests/connectors/`) — 55 tests :
  - [x] `YuhConnector` — 19 tests : parse count, montants, dates, heure None, card_last_four, merchant, import_hash, balance, matches_file
  - [x] `UBSConnector` — 14 tests : parse count, montants, heure carte/None virement, description_raw combinée, balance, IBAN normalisé, matches_file
  - [x] `CICConnector` — 22 tests : matches_file, get_account_sheets (RIB, account_type_hint, balance), parse_sheet CC+LA, amounts, currency EUR, date ISO, card_last_four, merchant, parse() agrège 2 feuilles → 5 tx
- [x] **Tests ImportService** (`src/tests/services/`) — 19 tests :
  - [x] Déduplication file_hash (même fichier 2×) et row-level (même tx, hash différent)
  - [x] `amount_chf` CHF = amount, EUR = amount × taux, fallback None si API down
  - [x] `_find_rule()` — description_raw, merchant_name, case-insensitive, no match, list vide
  - [x] `dry_run=True` — count correct, rien en DB
  - [x] `get_exchange_rate` — DB cache hit, API call mocké, stockage, doublon API, erreurs réseau/format
- [x] **Tests intégration** (`src/tests/integration/`) — 8 tests : chaîne complète CSV → parse() → run() → assert DB
- [x] **Tests résolution compte** (`src/tests/commands/`) — 7 tests :
  - [x] `import_yuh._find_account()` : 0 compte, 1 compte, 2+ comptes, compte inactif ignoré
  - [x] `import_ubs._find_account()` : IBAN absent, IBAN pas en DB, IBAN trouvé

---

## ✅ Phase 2A — Page Budget principale (livré 2026-04-22)
> Branche : `feature/phase-2a-budget-kpis`

- [x] **Pré-requis audit** : mettre à jour `documentation/schema_db_v2.mermaid` ✅ 2026-04-18
- [x] **Refactor architecture** : extraction app `budget/` depuis `transactions/` ✅ 2026-04-22
- [x] **`make test`** + pytest pre-commit hook ✅ 2026-04-22
- [x] URL `/budget/` → vue `budget_index(request)` → `budget/index.html` ✅ 2026-04-22
- [x] **Sankey cashflow** — ECharts 3 colonnes (income → pool → expense), gradient sombre→lumineux ✅ 2026-04-22
- [x] **KPIs row** : Entrées / Sorties / Disponible — clic KPI change tab ✅ (était déjà livré)
- [x] **Distribution donut** — ECharts, label centré, légende textuelle ✅ 2026-04-22
- [x] **Filtre période** : 1M / 3M / 1A + navigation ← → — session Django ✅ (déjà livré)
- [x] **Liste catégories** : icône + nom + montant ✅ (déjà livré)
- [x] **Design tokens JS** : `window.BRICBUDGET_TOKENS` exposé depuis `base.html` — plus de hex hardcodé ✅ 2026-04-22
- [x] **Seed réaliste** : `dev_seed_realistic` — 24 mois Genève, ratio revenus/dépenses 1.30× ✅ 2026-04-22
- [ ] **Deuxième passe icônes** — affinage visuel avec données réelles
- [ ] **Filtre catégories** : dropdown multi-select + toggle sous-catégories (issue #23)
- [ ] **Filtre compte** multi-select — session Django (issue #23)
- [ ] "Tout voir" → right panel `#panel-content` → `_panel_tx_list.html` (HTMX)
- [ ] Right panel état A : liste transactions + filtres complets
- [x] **Refactor JS charts** : `static/js/charts/` — `utils.js` + `sankey.js` + `donut.js`, `window.BricCharts` namespace ✅ 2026-04-22

---

## ✅ Phase 2B — Page catégorie (livré 2026-04-22)
> Objectif : `/budget/categorie/<slug>/` — drill-down catégorie avec Sankey sous-catégories
> Branche : `feature/phase-2a-budget-kpis`
> Issue GitHub : #22

### ✅ Livré session 1 (2026-04-22 matin)
- [x] ECharts 5.6.0 installé en local (`static/js/vendor/echarts.min.js`) — plus de CDN
- [x] Refactoring JS → `static/js/charts/utils.js` + `sankey.js` + `donut.js` (`window.BricCharts` namespace)
- [x] `slug` ajouté sur nœuds Sankey + segments Donut
- [x] URL `/budget/categorie/<slug>/` + vue `budget_category_detail()` + template `category_detail.html`
- [x] Navigation depuis liste catégories (`<a>` sur chaque ligne)
- [x] Navigation depuis Sankey (`onNodeClick`) + Donut (`onSegmentClick`)
- [x] Template : header breadcrumb + 3 KPIs + Sankey sous-catégories (direct, no pool) + liste transactions
- [x] Right panel overlay wired via `hx-on::after-request` sur le déclencheur HTMX (fix DOM tree)
- [x] **`panel_target` context var** dans `_panel_tx_row.html` — div fixe vs overlay, rétro-compatible ✅ 2026-04-28
- [x] **`#cat-tx-detail` div fixe** sous le donut dans `category_detail.html` panel_right ✅ 2026-04-28
- [x] **`close_on_back`** dans `_panel_tx_detail.html` — bouton ← contextuel (ferme overlay si source=category) ✅ 2026-04-28
- [x] **Alignement Cashflow ↔ Donut** — JS `offsetHeight` post-init, `flex flex-col gap-4` aside ✅ 2026-04-28
- [x] **Badge "Règle intelligente"** — corrigé : `rule` seulement (pas `ai`) ✅ 2026-04-28

### ✅ Livré session 2 (2026-04-22 après-midi)
- [x] **Seed réaliste Yuh** — import CSV réel (Yuh) + UBS + CIC en DB
- [x] **Sankey global — shape fix** : `layoutIterations: 0` → income en haut, expense en bas, plus de croisements
- [x] **Nœud `__disponible__`** — invisible (rgba 0,0,0,0 + opacity:0) pour équilibrer le pool quand revenus > dépenses
- [x] **Labels Sankey universels** : source→RIGHT, target→LEFT via `HIDDEN_NODES` set — fonctionne global ET catégorie
- [x] **Gradient links** : skip gradient pour `__disponible__` (opacity reste 0), couleur TARGET pour les autres
- [x] **Palette monochrome** : `_seg_factor(i, n)` distribue brightness 0.70→0.35 (min visible dark bg) — même couleurs Sankey + Donut
- [x] **Donut sous-catégories** dans `panel_right` de `category_detail.html` (donut + liste avec pastilles)
- [x] **KPI strip 3-col** sous le Sankey catégorie : Total · Transactions · Moyenne/tx (divide-x border-t)
- [x] **Navigation période** sur `category_detail.html` — composant `period_nav.html` réutilisé
- [x] **`set_period` redirect HTTP_REFERER** — redirige vers la page appelante (index ou catégorie)
- [x] **Animation Sankey** : 400ms `cubicOut` — réglage root level + series level (ECharts quirk)
- [x] **Soon badges** sur tous les boutons non-fonctionnels (`index.html` + `base_app.html`)

### ✅ Livré session 3 (2026-04-23) — bug fixes + CRUD BudgetTarget
- [x] **BudgetTarget → OneToOneField** : suppression `period`, objectif global par catégorie, migration safe avec déduplication
- [x] **CRUD objectif** : bouton crayon visible sur KPI catégorie + modal liste catégories (statut objectif) + formulaire pré-rempli
- [x] **Dropdown "Créer"** activé dans index.html (menu stylé, "Objectif mensuel" fonctionnel)
- [x] **CIC parser** : `_clean_merchant` strip codes alphanumériques avec chiffre (ex: ESSOF108)
- [x] **`_keyword_q()` helper** : `iregex` + `\y` word boundaries PostgreSQL pour les requêtes de règles
- [x] **Filtre tokens digit** : codes locaux exclus des chips wizard et de la suggestion initiale
- [x] **Filtre "PAIEMENT"** : `budget_categorize_transaction` applique le filtre noise (plus "toutes les tx CIC")
- [x] **Live preview** : `htmx.ajax()` direct + `data-*` attributes (remplace `hx-trigger` custom events)
- [x] **Submit disabled** si aucun keyword + guard 400 serveur
- [x] **Category picker** : titre transaction + × doré + badge sous-catégorie
- [x] **Rule preview** : liste scrollable complète + `merchant_name`
- [x] **Overspend** : couleur `text-expense` (orange-rouge) au lieu de gold
- [x] **`bb-scroll`** : thin scrollbar CSS dans `base.html`
- [x] **Panel ×** : supprimé du shell, chaque fragment gère son propre close

### Reste Phase 2B
- [x] **KPIs = onglets sélecteurs** : `[Transactions] [Sous-catégories] [Objectif]` — clic = `budget:set_cat_tab` → session `budget_cat_tab` ✅ 2026-04-24
- [x] **Cercles de progression SVG** : arc catégorie-colored autour icônes index.html + texte budget (% vert / CHF orange) ✅ 2026-04-24
- [x] **Re-import CIC** : homogénisation parseurs (SHA256 + `_normalize_merchant`) + flush + re-import complet 3902 tx ✅ 2026-04-28

---

## ✅ Phase 2C — Objectifs + Historique (livré 2026-04-24, session 5)
> Objectif : suivi objectifs mensuels par catégorie
> Branche : `feature/phase-2a-budget-kpis`

- [x] Composant `_gauge.html` réutilisable — SVG demi-cercle (`<circle>` + `stroke-dasharray` + `rotate(180)`), 5 usages dans `category_detail.html`
- [x] Filtres `gauge_fill(pct)` + `gauge_color(pct, threshold)` dans `budget_filters.py`
- [x] `BricCharts.initBar()` — bar chart ECharts : pill bars (`borderRadius: [999]`), y-axis gauche, zero line, `endLabel` "OBJECTIF", sans année dans labels
- [x] Vue `budget_set_period_month` + URL `/budget/period/month/<year>/<month>/` — clic barre → full redirect vers ce mois (session Django)
- [x] Historique mensuel 12 mois (`monthly_history`) dans `budget_category_detail()` — `TruncMonth + Sum`
- [x] Tab Objectif `panel_left` : bar chart historique + header "HISTORIQUE MENSUEL"
- [x] Tab Objectif `panel_right` : card Objectif avec large gauge (`w-44`) + 3 KPIs (Dépenses · Restant · Objectif mensuel)
- [x] KPI grid 3 colonnes égales + section headers Finary-style (blanc, uppercase, tracking-widest)
- [x] Mini gauge (`w-8`) dans tab strip + dans 4 cellules KPI
- ~~Clic barre → partial HTMX~~ — remplacé par full redirect (plus simple, même UX : la page entière se met à jour)

---

## 📅 Phase 2D — Sous-catégories + Multi-select (à planifier)
> Objectif : granularité sous-catégories + actions bulk

- [ ] Tab Sous-catégories : liste + Distribution donut (panel droit fixe)
- [ ] Multi-select transactions → barre contextuelle flottante (Pointer / Ignorer / Catégoriser)
- [ ] Right panel "Tout voir" : tous les filtres complets (montants + comptes + catégories + statut)

---

## ✅ Phase 2E — Wizard règle de catégorisation (livré en avance en Phase 1C — 2026-04-17)
> ~~Objectif : créer une règle depuis l'UI, appliquer en masse~~
> Livré en Phase 1C, pas en Phase 2E comme prévu initialement.

- [x] ~~`RuleWizardService.extract_tokens()`~~ — extrait inline dans `budget_panel_rule_create()` (views.py)
- [x] Toast "Catégorie modifiée" + CTA "Créer une règle" — bouton activé, `hx-get` dynamique via JS + `htmx.process()`
- [x] ~~Modale Step 1~~ — panel HTMX `_panel_rule_create.html` : chips tokens depuis `description_raw.split("|")[0]`
- [x] ~~Modale Step 2~~ — picker catégorie accordéon avec icônes (`_rule_cat_picker_row.html`) + preview count (`_panel_rule_preview.html`)
- [x] ~~Modale Step 3~~ — confirmation + bulk update via `budget_rule_create_submit()` (`_panel_rule_confirm.html`)
  - ~~`target_field="description_raw"`~~ → `"display_name"` depuis session 23
- [x] Toast intégré dans le panel de confirmation

---

## ✅ Phase 2C — Dark Theme + Design System (fait en avance — 2026-04-06)
> Objectif atteint pendant Phase 1B — design Finary en place avant même les données réelles

- [x] Palette Finary dans `tailwind.config` (tokens sémantiques — NE PAS utiliser hex brut dans les templates)
- [x] Dark theme complet : fond noir pur + glow bleu/vert/or, cartes `bg-surface-3 border-edge`
- [x] Composants de base : card (KPI, liste compte), sidebar active/hover, topbar, right panel
- [ ] Glassmorphism léger : `backdrop-blur` + `bg-opacity` sur les cartes — à revisiter si besoin
- [ ] Icônes catégories colorées avec glow subtil — à faire Phase 1B data components

---

## 📅 Phase 3A — Budget & Objectifs (Samedi 2026-05-31)
> Objectif : suivi budget comme Finary

- [ ] **Modal "Créer catégorie"** : nom + couleur (palette) + icône (grille)
- [ ] Saisie objectifs mensuels par catégorie (BudgetTarget)
- [ ] Vue Budget : cible / réalisé / écart / barre de progression
- [ ] Alertes visuelles dépassement (badge rouge "au-dessus de l'objectif")
- [ ] `is_system = True` sur catégories système → non supprimables dans l'UI

---

## 📅 Phase 3B — Polish + MVP (Samedi 2026-06-07)
> MVP V1 finalisé

- [ ] Historique BudgetResult par mois
- [ ] Archivage compte (`is_active = False`)
- [ ] Détection dépenses récurrentes (algo : même marchand + fréquence régulière)
- [ ] Revue UX globale — test avec données réelles
- [ ] `make backup` avant mise en production
- [ ] GitHub Actions CI — ruff + pytest (issue #19)

**MVP V1 cible : mi-juin 2026**

---

## ✅ Immédiat — Prérequis avant Phase 2F (livré 2026-04-28 → 2026-04-29)

- [x] **Commit** : `Makefile`, `views.py`, `base_app.html`, `dev_randomize_categories.py`, `import_all.py` — commit `b91f2d5`
- [x] **Homogénisation parseurs** : SHA1→SHA256 (migration 0005, max_length 40→64), `_normalize_merchant()` dans BaseConnector, `import re` module-level UBS — commit `2796450`
- [x] **Re-import complet** : flush 3902 tx + ImportLog, re-import propre avec parseurs corrigés
- [x] **`connectors/resolver.py`** : `detect_connector()` + `resolve_accounts()` + `AccountMatch` — ✅ 2026-04-29
- [x] **`BalanceSnapshot.computed_balance`** : `balance` nullable + `computed_balance` + propriétés `authoritative_balance` / `drift` + migration `0007` — ✅ 2026-04-29
- [x] **`ImportService`** : calcule `computed_balance` à chaque import, alerte si dérive > 0.01 — ✅ 2026-04-29
- [x] **Refactor commandes** : `import_yuh/ubs/cic/all` utilisent `resolve_accounts()`, `_find_account()` supprimé — ✅ 2026-04-29
- [x] **Tests mis à jour** : `test_account_resolution.py` teste `resolve_accounts()` directement — 88/88 ✅ 2026-04-29
- [x] **Documentation** : `schema_db_v2.mermaid` + `import_system.md` — resolver, dual balance, guides ajout banque/compte/carte — ✅ 2026-04-29

---

## ✅ Phase 2F — Import CSV UI (livré sessions 16-17, 2026-04-29 → 2026-04-30)
> Objectif : uploader un fichier CSV, voir l'analyse progresser, confirmer en un clic
> Branche : `feature/phase-2f-import`

### Session 1 ✅ — Infrastructure + page liste
- [x] `git checkout -b feature/phase-2f-import`
- [x] **`src/imports/apps.py`** — `ImportsConfig`
- [x] **`src/imports/urls.py`** — `app_name="imports"`, routes : `index / upload / confirm / create-account / <pk>/detail/`
- [x] **`src/imports/views.py`** — vues complètes
- [x] **`src/config/settings.py`** — `"imports"` dans `INSTALLED_APPS`
- [x] **`src/config/urls.py`** — `path("import/", include("imports.urls"))`
- [x] **`src/templates/imports/upload.html`** — historique groupé par file_hash + logos banques + expand CIC
- [x] **Sidebar** — item "Importer" actif (`app_name == 'imports'`)
- [x] **`make run`** → `/import/` accessible ✓

### Session 2 ✅ — Upload flow + comptes + bugs
- [x] **`import_upload` view** — multipart → tempfile → detect_connector → dry_run → session → fragment
- [x] **`_steps_result.html`** — cards animées + compte par compte + bouton confirm
- [x] **`_steps_error.html`** — card rouge + lien admin
- [x] **`import_confirm` view** — `ImportService(dry_run=False)` + `HX-Redirect /budget/`
- [x] **`_import_detail.html`** — panel droit détail ImportLog
- [x] **`connectors/resolver.py`** — `AccountNotFound` exception + résolution Yuh `first()` au lieu de `get()`
- [x] **`banks_config.py`** — config banques connues (Yuh, UBS, CIC, Boursorama, Finpension)
- [x] **`seed_banks`** — commande idempotente depuis `banks_config.py`
- [x] **`seed_accounts`** — wizard interactif `getpass` pour IBAN/RIB sensibles
- [x] **`seed_categories`** — commande isolée (catégories seules, pas banques/comptes)
- [x] **`CheckingAccount.iban` nullable** — `unique=True, null=True` (SQL NULL ≠ NULL)
- [x] **`Account.Currency` choices** — CHF, EUR, GBP, USD
- [x] **`ImportLog.file_hash` max_length=64** — SHA256 (était 40 pour SHA1)
- [x] **`_account_file_hash()`** — hash dérivé par feuille CIC pour `unique=True` ImportLog
- [x] **`seen_in_batch`** — dédup intra-fichier avant `bulk_create`
- [x] **Catégories par défaut** — revenus (≥0) / inconnu (<0) quand aucune règle ne matche
- [x] **UBS savings** — `matches_file` scan dynamique lignes 3-12 (variante 8 ou 9 lignes metadata)
- [x] **CIC `parse_sheet()`** — appelé directement au lieu de `parse(**kwargs)`
- [x] **Bug `float * Decimal`** — `amount = Decimal(str(...))` dans fallback catégorie (services.py)

### Cas edge validés ✅
- [x] Fichier déjà importé → +0 / "Aucune nouvelle transaction"
- [x] Compte non trouvé → `_steps_create_account.html` inline + lien admin
- [x] CIC multi-feuilles → breakdown par compte dans steps 2 et 3
- [x] Yuh sans IBAN → `first()` + `AccountNotFound` si aucun compte

### Session 3 ✅ — Graphique Activité + logos cohérents (2026-05-01)
- [x] **Redesign page** : Activité (hero gauche) + Historique + Importer + Synchronisation (droite)
- [x] **Graphique Activité** `static/js/charts/activity.js` — `BricCharts.initActivity` — bar chart empilé par banque, filtres 1M/3M/1A + Nouvelles/Total
- [x] **`base_app.html`** — `{% block panels_align %}` pour override flex alignment par page
- [x] **Template tag `{% bank_icon_url %}`** `transactions/templatetags/bank_icons.py` — résolution SVG→PNG depuis tout template (volume faible)
- [x] **Composant `bank_logo.html`** `components/banks/bank_logo.html` — cercle icône : SVG = fond sombre + invert, PNG = fond blanc

### Session 4 ✅ — Bug fixes (2026-05-02)
- [x] **CHF partout** — `amount_chf|default:amount` dans `_panel_tx_row` + `_panel_tx_detail` + 9 agrégats views.py (`Sum(Coalesce)`)
- [x] **Picker catégorie in-page** — `source=category` + `detail_target=#cat-tx-detail` propagé toute la chaîne HTMX
- [x] **Toast depuis category context** — `hx_trigger` extrait avant le `if source` dans `budget_categorize_transaction`
- [x] **Layout polish** — sticky supprimé des asides panel_right, `overflow-hidden` sur cashflow-card, bouton "+" Objectif réduit
- [x] Merge `development` ← `feature/phase-2f-import`

### Watcher (Phase 6 — UI SOON)
- [ ] Section "Synchronisation automatique" — toggle désactivé + SOON badge

---

## 📅 Phase 3A — Patrimoine > Comptes bancaires (planifiée 2026-04-28)
> Objectif : page `/patrimoine/comptes/` + détail compte — inspirée Finary
> Spec complète : `documentation/ui_patrimoine_specs.md`

### Session 1 — Infrastructure + liste comptes
- [ ] **Nouvelle app `src/patrimoine/`** — `apps.py`, `urls.py`, `views.py`
- [ ] **Sidebar refacto** : "Comptes (SOON)" → "Patrimoine ▼" collapsible + sous-items
  - "Comptes bancaires" actif + "Livrets" SOON + "Actions" SOON
  - Toggle JS minimal + session `sidebar_patrimoine_open`
- [ ] **Vue `patrimoine_comptes_index()`** → `patrimoine/comptes/index.html`
  - Comptes groupés par banque + solde (dernier `BalanceSnapshot`)
  - KPI total consolidé
  - Panel right : donut répartition par compte (ECharts, `BricCharts`)
- [ ] **Tab Comptes** : liste expand/collapse HTML natif (`<details>/<summary>`)

### Session 2 — Transactions + détail compte
- [ ] **Tab Transactions** + filtres HTMX (montants / catégories / état) — même pattern Budget
- [ ] **Vue `patrimoine_compte_detail(id)`** → `patrimoine/comptes/detail.html`
  - Panel right statique : Banque / Devise / Type / Taux / IBAN masqué / BIC
  - Toggle afficher IBAN (JS local)
  - 3-dot menu : Modifier (modal) / Supprimer (is_active = False)
- [ ] **Area chart balance** : timeline `BalanceSnapshot` → ECharts line chart
- [ ] **Réutilisation partials budget** : `_panel_tx_row.html`, `_panel_tx_detail.html`, `_panel_category_picker.html`

---

## 📅 Phase 3B-old — Budget & Objectifs (rebaptisée, anciennement Phase 3A)
> (contenu identique, juste renumérotée pour libérer Phase 3A)
> Samedi 2026-05-31

- [ ] **Modal "Créer catégorie"** : nom + couleur (palette) + icône (grille)
- [ ] Saisie objectifs mensuels par catégorie (BudgetTarget)
- [ ] Vue Budget : cible / réalisé / écart / barre de progression
- [ ] Alertes visuelles dépassement (badge rouge "au-dessus de l'objectif")
- [ ] `is_system = True` sur catégories système → non supprimables dans l'UI

---

## ~~Phase 3B-synthèse~~ — SKIP (décision 2026-04-28)
> La Synthèse Finary = Patrimoine brut (61k€) avec ETFs + Finpension. Données inexistantes.
> → Phase 4 quand les données patrimoine complet existent.
> Le prototype `synthese/index.html` reste intact (données hardcodées, non déployé).

## 📅 Phase 2G — CRUD règles + classification + déploiement (session 20, 2026-05-02)
> Branche : `feature/phase-2g-rules-crud`
> Critères : règles exportées + classification complète + tests passants

### T0 — Import storage + fix computed_balance ✅ (2026-05-06)
- [x] **`imports/storage.py`** — chiffrement Fernet + stockage fichiers importés
- [x] **`ImportLog`** : champs `storage_path`, `storage_encrypted`, `storage_error`, `date_min`, `date_max`
- [x] **`Transaction.import_log`** : `SET_NULL → CASCADE` + `signals.py` pre_delete
- [x] **`Account.iban`** : champ centralisé (migration 0011)
- [x] **Fix `computed_balance` rétroactif** : `date__lt=snapshot_date` dans `services.py`
- [x] **Templates** : `_steps_already_imported.html`, `_steps_account_picker.html`, `_steps_result.html`
- [x] **Tests** : `test_import_storage`, `test_import_zero_tx`, `test_balance_snapshots`, `test_cascade_and_signals`, `test_hash_stability` — **171 tests passent**
- [x] **Audit système d'import** — verdict : solide (close issue #35)

### T1 — CRUD règles ✅ (2026-05-02)
- [x] **Panel `_panel_rules_list.html`** — chargé via HTMX dans `#modal-content` depuis Paramètres → "Gérer les règles intelligentes"
- [x] **`_rule_row.html`** — lecture inline : toggle actif/inactif, supprimer (hx-confirm), éditer au hover
- [x] **`_rule_row_edit.html`** — formulaire inline avec picker catégorie/sous-catégorie (layout identique `_cat_picker_row.html`)
- [x] **5 nouvelles vues** : `budget_panel_rules_list`, `rule_toggle_active`, `rule_delete`, `rule_row_edit`, `rule_edit_submit`
- [x] **Helper `_cats_with_subcats()`** — 2 requêtes sans N+1
- [x] **Dropdown Créer** (w-80) : icônes Finary folder/sparkles/bullseye + labels Finary (issues #33 #34 SOON)
- [x] **Dropdown Paramètres** (w-80) : sparkles règles intelligentes, section Affichage supprimée
- [x] **`make lint` + `make check`** ajoutés au Makefile
- [x] **Icônes sous-catégories dans `_rule_row.html`** — fond light `colour_hex+40` comme `category_detail.html`

### T2 — Créer une règle standalone (Issue #33) ✅ (2026-05-06)
- [x] Formulaire de création dans le dropdown "Créer" — chips keywords, preview live, warning overwrite, confirmation

### T2b — display_name champ stocké + cleanup UI legacy ✅ (2026-05-06, refacto session 24)
- [x] **`Transaction.display_name`** — `CharField(max_length=300)` stocké (migration 0013)
- [x] **`TransactionDict`** — champ `display_name: str` ajouté
- [x] **`_normalize_merchant()`** dans `BaseConnector` — strip `;`/`:`, collapse espaces, uppercase
- [x] **`_clean_description()`** dans `BaseConnector` — split ` | ` (UBS) + normalize. Minimal intentionnel.
- [x] **`CIC._clean_merchant()`** — 2 regexes structurelles CIC (préfixe verbe+date + CARTE XXXX). Rien d'autre.
- [x] **3 connectors mis à jour** — Yuh, UBS, CIC populent `display_name`
- [x] **`recalculate_display_names`** management command — backfill 4104 tx existantes
- [x] **`CategorizationRule.TargetField.DISPLAY_NAME`** — nouvelle valeur, default changé (migration 0014)
- [x] **`_match_rule()`** — utilise `display_name` pour DISPLAY_NAME + MERCHANT_NAME (legacy)
- [x] **6 templates** nettoyés de tout `merchant_name`/`description_raw` display legacy
- [x] **Recherche + chips** depuis `display_name` (plus `description_raw`)
- [x] **171 tests passent**

### T3 — Créer une catégorie (Issue #34) ✅ (2026-05-12)
- [x] Panel "Nouvelle catégorie" depuis le dropdown "Créer" — grille 40 icônes curated + palette 8 cols + steps JS
- [x] Panel "Gérer les catégories" — liste annotée (subcat_count, tx_count, rules_count) + détail (sous-cats, règles)
- [x] Bouton "Supprimer" sur catégories/sous-catégories personnalisées + modal warning (counts impactés)
- [x] Bouton delete sous-catégorie dans `_cat_picker_row.html` (hover-reveal sur badge "perso", `group/subrow`)
- [x] Fix priorité règles : `Max("priority")` auto-increment (était hardcodé `10`)
- [x] Fix Z-index dropdown derrière panel Distribution : `relative z-[1]` sur `panel_left`
- [x] Click-outside handler `<details>` dropdowns (catégories + comptes) — `document.addEventListener('click'...)`
- [x] Convention UI : zéro abréviation ("transactions", "sous-catégories" — plus de "tx", "sous-cat")
- [x] Style liste → cartes individuelles (`space-y-1.5`, `bg-surface-2/50 border border-edge/30`)
- [x] 3 nouveaux fichiers tests : `test_categorization_priority`, `test_rule_priority_autoincrement`, `test_import_decimal_precision`
- [x] **186 tests passent**

### T4 — apply_rules management command (Issue #32)
- [ ] `transactions/management/commands/apply_rules.py` — applique toutes les règles actives en batch
- [ ] `make apply-rules`

### T5 — QA fixes pré-classification (Issue #29)
- [ ] Logos restants : `_steps_create_account.html` + `_import_detail.html` → migrer vers `{% bank_icon_url %}` + `bank_logo.html`
- [ ] Fichiers importés archivés avec UUID : `ImportLog.file_path` (nullable CharField) + migration
- [ ] Toggle virement interne : filtrer les virements internes du total dépenses
- [ ] Descriptions UBS : nettoyer les descriptions parasites UBS

### T6 — Budget Paramètres dropdown (Issue #30)
- [ ] Activer le bouton Paramètres (actuellement disabled + badge SOON)
- [ ] Toggle montants entiers / avec décimales
- [ ] Exporter les règles de catégorisation → JSON téléchargeable
- [ ] Lien ⚙ Gérer les catégories → admin Django

### Classification + déploiement
- [ ] **Session classification** : catégoriser toutes les transactions Yuh + CIC (~4h)
  - Prérequis : export des règles AVANT de commencer (`make export-rules`)
  - Objectif : 0 transaction "Non catégorisé" sur les 12 derniers mois
- [ ] **Merge `feature/phase-2g-rules-crud` → development → main** (PR GitHub)
- [ ] **Tag v0.1.0** — premier déploiement utilisable
- [ ] `make backup` → snapshot DB avant mise en prod

---

## 🔒 Phase 2H — Sécurité & Déploiement Railway (Milestone #18)
> Branche : `feature/phase-2h-deploy`
> Prérequis : Phase 2G mergée sur main
> Critères : app accessible sur Railway, login protégé, CSS/JS chargés, /admin/ caché

### T1 — Settings HTTPS prod (Issue #36) 🔴 BLOQUANT
- [ ] Section `# 11. Production security` dans `settings.py`
- [ ] `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`
- [ ] `SESSION_COOKIE_AGE = 60 * 60 * 8` (expire après 8h d'inactivité)
- [ ] `.env.example` mis à jour avec les nouvelles variables

### T2 — Static files + Whitenoise (Issue #39) 🔴 BLOQUANT
- [ ] `pip install whitenoise`
- [ ] `STATIC_ROOT` défini dans `settings.py`
- [ ] `WhiteNoiseMiddleware` après `SecurityMiddleware`
- [ ] `STORAGES` avec `CompressedManifestStaticFilesStorage`
- [ ] `make collectstatic` dans Makefile

### T3 — Rate limiting login — django-axes (Issue #37) 🟠 IMPORTANT
- [ ] `pip install django-axes`
- [ ] `INSTALLED_APPS`, `MIDDLEWARE`, `AUTHENTICATION_BACKENDS` mis à jour
- [ ] `python manage.py migrate axes`
- [ ] Lockout après 5 tentatives, débloqué après 1h

### T4 — URL /admin/ cachée (Issue #38) 🟠 IMPORTANT
- [ ] `ADMIN_URL = config("ADMIN_URL", default="admin/")` dans `settings.py`
- [ ] `urls.py` mis à jour : `path(settings.ADMIN_URL, admin.site.urls)`
- [ ] Variable Railway : `ADMIN_URL=<valeur secrète>`

### T5 — Logging prod stdout (Issue #40) 🟡 UTILE
- [ ] `LOGGING` configuré dans `settings.py` (stdout → Railway dashboard)
- [ ] `LOG_LEVEL` en variable d'env

### T6 — Setup Railway + déploiement initial (Issue #41)
- [ ] Compte Railway créé, projet connecté au repo GitHub
- [ ] Toutes les variables d'env positionnées
- [ ] `gunicorn` installé + `Procfile` créé
- [ ] Build command : `collectstatic` + `migrate`
- [ ] App accessible sur `https://<projet>.railway.app`
- [ ] Login, import CSV, /admin/ secret → tout testé

---

## 📦 Phase Bonus — si on a le temps

- [ ] **Note inline** — ajouter/modifier texte libre sur une transaction
- [ ] ~~**Merchant name inline**~~ — supprimé : l'user ne doit pas pouvoir modifier le nom brut banque, risque de chaos
- [ ] **Toggle CHF/EUR** dans la topbar + bouton "flouter les montants" — à faire en même temps que taux de change

---

## 📦 Backlog — Phase 4+ (pas de date)

### Phase 4 — Patrimoine Net

**Architecture Asset/Holding — Notes de conception (2026-04-06)**

> Problème : Finary classe en Compte Bancaire / Livrets / Actions & Fonds / Fond Euro / Crypto.
> Notre modèle actuel (`Account.account_type`) ne suffit pas — Finpension contient des ETFs + du cash.
> Solution : architecture 2 couches.

**Couche 1 — `Account.account_category` (à migrer tôt, dès Phase 4)**
```
bank | savings | investment | crypto | other
```
→ Simple `CharField` sur `Account`. Sert de classification institutionnelle (enveloppe).
→ Migration simple, pas de nouvelle table.

**Couche 2 — `Asset` + `Holding` (Phase 4 ou 5 selon Finpension)**
```python
class Asset(Model):
    name = CharField()          # ex : "Yuh Compte Courant", "MSCI World ETF"
    ticker = CharField()        # ex : "IWDA" — null si cash
    asset_class = CharField()   # cash | equity | bond | euro_fund | crypto
    currency = CharField()

class Holding(Model):
    account = ForeignKey(Account)
    asset = ForeignKey(Asset)
    quantity = DecimalField()   # null si cash (on utilise value directement)
    value = DecimalField()      # valeur en devise du compte
    value_chf = DecimalField()  # valeur CHF (ExchangeRate)
    as_of = DateField()         # date du snapshot
```

**Mapping vers Finary :**
| Finary | account_category | asset_class |
|--------|-----------------|-------------|
| Compte Bancaire | `bank` | `cash` |
| Livrets | `savings` | `cash` |
| Actions & Fonds | `investment` | `equity` / `bond` |
| Fond Euro | `investment` | `euro_fund` |
| Crypto | `crypto` | `crypto` |

**Cas concrets :**
- Yuh C/C → 1 Account (`bank`) → 1 Holding (`cash`)
- CIC Livret A → 1 Account (`savings`) → 1 Holding (`cash`)
- Finpension LP → 1 Account (`investment`) → N Holdings (1 ou 2 ETFs + 1 cash)
- Finpension 3a → 1 Account (`investment`) → N Holdings (ETFs)

**Quand implémenter :**
- `account_category` sur Account → dès que les données réelles arrivent (Phase 4)
- `Asset` + `Holding` → quand on parse Finpension (Phase 4) ou Yuh investissements (Phase 5)
- NE PAS anticiper avant d'avoir le CSV Finpension en main

---

**Tâches Phase 4 :**
- [ ] Migration `Account.account_category` (`bank | savings | investment | crypto | other`)
- [ ] `Asset` model + `Holding` model (voir architecture ci-dessus)
- [ ] Parseur CIC France ✅ déjà fait Phase 1A — à vérifier si complet pour bilans
- [ ] Parseur Finpension LP + 3a (CSV ou PDF à identifier)
- [ ] Import Holdings depuis CSV Finpension → `Asset` + `Holding` auto-créés
- [ ] Page Synthèse avec données réelles (remplace données fictives `synthese/index.html`)
- [ ] Courbe patrimoine net dans le temps (BalanceSnapshot + Holding.as_of)
- [ ] Treemap allocation par classe d'actif
- [ ] Consolidation multi-devises → CHF (ExchangeRate déjà en place)

### Phase 5 — Investissements Yuh
- [ ] Modèles Instrument + InvestmentPosition + InvestmentTransaction
- [ ] Parser transactions invest. Yuh (BUY/SELL)
- [ ] Calcul coût de revient moyen pondéré
- [ ] Vue positions : +/- value latente, performance %
- [ ] PriceHistory : job quotidien (yfinance ou Alpha Vantage)

### Phase 6 — Automatisation
- [ ] Watcher iCloud Drive (Django-Q cron)
- [ ] Claude API fallback catégorisation
- [ ] n8n workflow Gmail → Finpension auto-import
- [ ] Accès Tailscale (Nginx)

### Phase 7 — Comptes UK (Carys)
- [ ] Identifier banque Carys (Monzo / Starling / Revolut / HSBC)
- [ ] Parseur UK
- [ ] AccountAccess : Carys owner + Emmanuel viewer
