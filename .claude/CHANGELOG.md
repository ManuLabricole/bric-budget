# CHANGELOG — BudgetTracker

## 2026-05-12 — Session 26 : Phase 2G T3 — Catégories CRUD + panel Gestion + tests (VSCode)

**Contexte**
Livraison de T3 (issue #34) : créer et supprimer des catégories/sous-catégories depuis l'UI sans passer par l'admin Django. Également : panel "Gérer les catégories", 3 nouveaux fichiers de tests, fix priorité règles, fix Z-index, click-outside dropdowns, et redesign UI (cartes vs tableau, suppression des abréviations).

**Livré**

*Catégories CRUD — nouvelles vues (6)*
- `budget_panel_category_create` — GET : panel création, grille 40 icônes curated (`_CURATED_ICONS` module-level, pas de filtre "déjà utilisé"), palette 8 colonnes
- `budget_category_create_submit` — POST : catégorie principale ou sous-catégorie, validation doublon, slug auto-généré
- `budget_panel_category_delete_confirm` — GET : modal warning avec counts (transactions, sous-catégories, règles) impactés
- `budget_category_delete` — POST : suppression + `HX-Redirect /budget/`
- `budget_panel_category_manage` — GET : liste toutes catégories annotées (subcat_count, tx_count, rules_count)
- `budget_panel_category_manage_detail` — GET : détail catégorie (sous-cats + règles)

*Nouveaux templates (4)*
- `_panel_category_create.html` — steps JS show/hide (type → icône → couleur → nom)
- `_panel_category_delete_confirm.html` — warning + confirmation suppression
- `_panel_category_manage.html` — liste catégories avec stats et chevron
- `_panel_category_manage_detail.html` — cartes individuelles sous-cats + règles, badge "perso", hover-reveal delete

*UI index.html*
- Dropdown "Créer" : entrée "Nouvelle catégorie" (SOON → fonctionnel)
- Dropdown "Paramètres" : lien admin Django → HTMX "Gérer les catégories"
- Fix Z-index : `relative z-[1]` sur `panel_left` — dropdown "Tous les comptes" ne passe plus derrière le donut
- Click-outside handler `document.addEventListener('click', ...)` pour les `<details>` catégories et comptes

*`_cat_picker_row.html`*
- Bouton suppression sous-catégorie perso : sibling `<div class="group/subrow flex">` + delete button `opacity-0 group-hover/subrow:opacity-100` — évite le nesting button-in-button (HTML invalide)

*Fix priorité règles*
- `Max("priority")` depuis `django.db.models` dans les 2 vues de création de règles (était hardcodé `10`)
- Les 5 règles existantes re-numérotées 1→5 via shell Django

*3 nouveaux fichiers de tests*
- `test_categorization_priority.py` — 5 tests : règle priorité haute gagne, seul match, inactive ignorée, no match, case-insensitive
- `test_rule_priority_autoincrement.py` — 4 tests : première règle = priorité 1, séquentiel croissant, max+1, get_or_create n'écrase pas
- `test_import_decimal_precision.py` — 6 tests : 0.01 CHF exact, standard 2 déc, CHF=amount, EUR×taux, None si API down, zéro sans crash
- **186 tests passent**

*Convention UI*
- Zéro abréviation : "tx" → "transactions", "sous-cat" → "sous-catégories" dans tous les templates de gestion
- Style liste → cartes individuelles (`space-y-1.5`, `bg-surface-2/50 border border-edge/30 rounded-xl`) au lieu de `divide-y`

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Icônes categories | 40 icônes curated, aucun filtre "déjà utilisé" | 139 catégories pour 115 icônes max → unicité impossible. Une icône peut servir à plusieurs catégories. |
| Stacking context Z-index | `relative z-[1]` sur panel gauche | `backdrop-blur-xl` crée un nouveau stacking context, l'ordre DOM seul détermine la priorité. Fix minimal, pas de restructuration DOM. |
| `<details>` click-outside | `document.addEventListener('click', ...)` avec `!el.contains(e.target)` | Comportement natif absent. Ajout minimal JS, pas de lib externe. |
| Style détail catégorie | Cartes individuelles plutôt que tableau/dividers | Plus cohérent avec le style général de l'app (liste transactions), moins rigide visuellement. |
| Abréviations UI | Banni : "tx", "sous-cat" → mots complets | Convention explicite demandée par Emmanuel. |

**Bugs rencontrés**
- `Count("transaction")` → FieldError : le `related_name` dans Django ORM est `"transactions"` (pas le nom du modèle). Même pattern pour `Count("rules")` (pas `"categorizationrule"`)
- Icon picker : 1 seule icône affichée → le filtre `used_icons` excluait les 40 curated (toutes déjà utilisées). Fix : supprimer tout filtrage.
- Imports ruff dans tests : ordre stdlib/third-party/local incorrect → `ruff check --fix`
- `<button>` imbriqué dans `<form><button>` pour delete → HTML invalide. Fix : wrapper `<div class="group/subrow flex">` + form `flex-1` + delete button sibling.

**Reste à faire**
- T4 : `apply_rules` management command (issue #32)
- T5 : QA fixes (issue #29)
- T6 : Budget Paramètres dropdown (issue #30)
- Session classification manuelle (~4h)
- Merge `feature/phase-2g-rules-crud` → development → main + tag v0.1.0

## 2026-05-08 — Session 24 : Code review + fixes services.py + refacto _clean_description (VSCode)

**Contexte**
Session de revue et polish avant merge de `feature/phase-2g-rules-crud`. Pas de feature nouvelle — corrections ciblées issues de la code review + décision architecturale sur le nettoyage des descriptions bancaires.

**Livré**

*Prompt audit CTO*
- `.claude/commands/audit_cto.md` — nouveau prompt `/audit_cto` mode CTO agressif : 9 étapes (sécurité exploitable, atomicité, migrations, performance, Bandit, observabilité, résilience, conformité, tests), CVE Django actives, exploit scenarios obligatoires sur 🔴/🟠, référence cookiecutter-django

*Fixes `services.py` (issues code review)*
- `import datetime as _dt` + `import logging` déplacés en tête de module (était `import datetime as _dt` en milieu de fonction)
- `logger = logging.getLogger(__name__)` ajouté — plus de `print()` dans le code de prod
- `print(...)` → `logger.warning(...)` dans `get_exchange_rate()` (format `%s` idiomatique)
- `ExchangeRate.objects.create()` → `get_or_create(defaults={"rate": rate})` — protection race condition si deux imports simultanés sur même date/devise

*Refacto `_clean_description()` — décision architecturale*
- **Décision** : ne nettoyer que ce qui est structurellement du bruit bancaire, jamais ce qui est sémantiquement ambigu
- `_normalize_merchant()` simplifié : retire `;` et `:`, collapse espaces, uppercase (plus de title-case)
- `_clean_description()` réduit à 2 lignes : split ` | ` (UBS) + normalize. Intentionnellement minimal.
- `CIC._clean_merchant()` : 2 regexes structurelles certaines (préfixe verbe+DDMM imposé norme FR + `CARTE XXXX`) — rien d'autre
- 4 tests connectors mis à jour (uppercase au lieu de title-case)
- **171 tests passent, ruff OK**

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `_clean_description` agressivité | Nettoyage minimal — seulement bruit structurel certain | Les regexes de strip (codes ref, géocodes, ATM) supprimaient de l'information potentiellement utile pour les règles. Risque de faux positifs. |
| `print()` → `logging` | `logger.warning()` dans tout le code de service | `print()` invisible derrière Gunicorn en prod |
| `ExchangeRate.objects.create` → `get_or_create` | Thread-safe par défaut | Race condition si 2 imports simultanés sur même date/devise |
| title-case → uppercase | `_normalize_merchant()` retourne uppercase | Plus proche de la donnée banque réelle, pas d'interprétation |

**Reste à faire**
- T3 : Créer catégorie depuis dropdown "Créer" (issue #34)
- T4 : `apply_rules` management command (issue #32)
- Session classification manuelle (~4h)
- Merge `feature/phase-2g-rules-crud` → development → main

## 2026-05-06 — Session 23 : Phase 2G — display_name champ stocké + cleanup UI legacy (VSCode)

**Contexte**
Refactoring architectural majeur : `display_name` devient un champ stocké en DB (pas une property), calculé à l'import par `_clean_description()` bank-agnostic dans `BaseConnector`. Objectif : les règles de catégorisation matchent sur un texte propre et uniforme, indépendant de la banque source. Migration + backfill 4104 transactions + nettoyage complet de l'UI legacy (`merchant_name`/`description_raw`).

**Livré**

*Champ display_name — modèle + migration + backfill*
- `Transaction.display_name` — `CharField(max_length=300, blank=True, default="")`, stocké (pas une property), queryable par l'ORM
- Migration `0013_transaction_display_name.py`
- `TransactionDict` TypedDict : champ `display_name: str` ajouté entre `description_raw` et `merchant_name`
- `ImportService.run()` : `display_name=tx["display_name"]` à la création des transactions
- Management command `recalculate_display_names` — backfill de tous les transactions existants (`bulk_update` par batch de 500), flags `--dry-run` et `--limit` — **4104 transactions mises à jour**
- `make recalculate-display-names` ajouté au Makefile

*`_clean_description()` — fonction bank-agnostic dans BaseConnector*
6 règles appliquées dans l'ordre :
1. Split avant ` | ` (artefact UBS multi-champs)
2. Strip préfixes bancaires français + date DDMM (PAIEMENT PSC, VIR SEPA, RETRAIT DAB...)
3. Strip `CARTE XXXX` et tout ce qui suit (CIC)
4. Strip géocode UBS (`;0102 Lonay` ou `;CH 1228 Ouates`)
4b. Strip montant ATM en tête (après RETRAIT DAB : `280,00 CHF FILIALE...`)
5. Strip tokens référence en fin (contiennent chiffre + 4+ chars : `HIR082612500020475`)
6. Supprimer mots consécutifs doublons (`LONAY LONAY` → `LONAY`)
→ Fallback sur raw normalisé si résultat vide

*Connectors mis à jour*
- `connectors/yuh/parser.py` : utilise RECIPIENT/SENDER en priorité, `_clean_description` en fallback
- `connectors/ubs/parser.py` : description1 seulement (description2 supprimée) → `_clean_description`
- `connectors/cic/parser.py` : `_clean_merchant` remplacé par `_clean_description`
- Tous retournent `display_name=display_name` + `merchant_name=display_name` (pré-fill override)

*Règles de catégorisation — display_name comme cible canonique*
- `CategorizationRule.TargetField.DISPLAY_NAME = "display_name"` — nouvelle valeur dans les choices
- Default `target_field` → `DISPLAY_NAME` (était `MERCHANT_NAME`)
- Migration `0014_categorization_rule_display_name_target.py`
- `_match_rule()` dans `services.py` : branche sur `DISPLAY_NAME` et `MERCHANT_NAME` (legacy) → `tx["display_name"]`, `DESCRIPTION_RAW` → `tx["description_raw"]` (backward compat)
- `_keyword_q()` dans `views.py` : déjà sur `display_name__iregex` ✓
- Les 2 vues `rule_create_submit` et `rule_create_standalone_submit` : `"target_field": "display_name"` (était `"description_raw"`)
- Recherche libre dans panel transactions : `display_name__icontains` (était `merchant_name | description_raw`)
- Tokenisation chips règles : depuis `tx.display_name` (était `tx.description_raw.split("|")[0]`)

*Nettoyage UI — merchant_name/description_raw legacy supprimé*
- `_panel_tx_row.html` : `tx.display_name` ✓ (déjà OK)
- `_panel_tx_detail.html` : `tx.display_name` ✓ (déjà OK)
- `_rule_standalone_preview_row.html` : `tx.display_name` (était `merchant_name or description_raw`)
- `_panel_category_picker.html` : `tx.display_name` (était `merchant_name|default:description_raw`)
- `_modal_rule_intro.html` : `tx.display_name` (était `{% if merchant_name %}...{% else %}description_raw{% endif %}`)
- `_rule_live_preview.html` : `tx.display_name|upper` (était `merchant_name|upper or description_raw`)

*Fixes UI divers (début de session)*
- Filtre compte dans panel "Tout voir" — HTMX partial swap au lieu de full page reload (vue HTMX-aware)
- Dropdown compte clippé — `min-w-[200px]` → `w-56` fixe (overflow-y: auto créait un stacking context qui clippait le dropdown)

*Tests*
- Tous les dicts `tx` minimaux dans `test_import_service.py` : `display_name` ajouté
- **171 tests passent, ruff OK**

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| display_name stocké ou property | Champ stocké (`CharField`) | ORM filtering pour les règles — une property ne peut pas être filtrée avec `Q()` |
| merchant_name | Conservé en DB, pré-rempli = display_name | Override manuel utilisateur (Phase future) — la séparation reste utile |
| target_field MERCHANT_NAME | Legacy, alias de display_name | Existing rules continuent de fonctionner sans migration de données |
| description_raw | Intouché, immuable | Audit trail banque — on ne touche jamais au raw |
| UBS description2 | Supprimée | description1 seule suffit + `_clean_description` produit un résultat propre |

**Bugs rencontrés**
- Règle 4 UBS manquait les géocodes `;CH 1228` (country code + postal) → regex étendue `(?:[A-Z]{2}\s+)?`
- RETRAIT DAB laissait `280,00 CHF` après strip du préfixe → ajout règle 4b strip montant ATM
- `LONAY LONAY` artefact UBS → ajout règle 6 dédoublonnage mots consécutifs
- `Q` import top-level dans views.py devenu unused → F401 ruff → supprimé

**Reste à faire (Phase 2G)**
- T3 : Créer catégorie depuis dropdown Créer (issue #34)
- T4 : `apply_rules` management command (issue #32)
- Session classification manuelle (~4h)
- Merge → development → main + tag v0.1.0

---

## 2026-05-06 — Session 22 : Phase 2G T2 — Règle standalone + UI fixes (VSCode)

**Contexte**
Implémentation complète de T2 : créer une règle de catégorisation directement depuis le dropdown "Créer", sans passer par une transaction existante. Système de chips keywords, preview live, warning overwrite, confirmation. Petits fixes UI découverts en cours.

**Livré**

*T2 — Règle standalone*
- **3 nouvelles vues** dans `budget/views.py` :
  - `budget_panel_rule_create_standalone` : formulaire chips + picker catégorie
  - `budget_rule_standalone_preview` : preview live (count + 5 premières tx) via `GET ?kw[]=…`
  - `budget_rule_create_standalone_submit` : flow 2 étapes (overwrite check → create + bulk apply)
- **4 nouveaux templates** :
  - `_panel_rule_create_standalone.html` — chips input (Enter = ajoute, Backspace = retire), picker catégorie, `standaloneFirePreview()` JS
  - `_rule_standalone_preview.html` — count + liste 5 premières + "et X autres · Voir plus"
  - `_rule_standalone_preview_row.html` — rangée 5 colonnes alignées : date | logo banque | icône cat | description truncate | montant
  - `_panel_rule_overwrite_warning.html` — liste transactions écrasées, "Confirmer quand même" (force=1)
- **Logique AND-cumulatif** : chips "MIGROS" + "CAROUGE" = keyword composé "MIGROS CAROUGE" → `_keyword_q()` existant gère nativement
- **Warning overwrite** : check `categorization_source="rule"` avant création, affichage spécifique si conflits, skip sur `force=1`
- **Wizard existant** (`budget_rule_create_submit`) : même flow force ajouté pour cohérence
- **Dropdown "Créer"** : bouton "Nouvelle règle intelligente" activé (était SOON), `openModal()` inline

*Fixes UI*
- Modal élargie `max-w-md → max-w-xl` dans `base_app.html`
- "_panel_rule_confirm.html" : bouton "Retour à la liste" → "Fermer" (closeModal() → budget, pas une liste)
- Bouton "Créer" aligné sur "Tout voir" et "Paramètres" (suppression border gold + font-medium superflus)
- "Nouvel objectif de dépense" : `text-left` ajouté (était centré)
- `hover:text-gold` ajouté sur les 3 boutons toolbar (Tout voir / Créer / Paramètres) — cohérence avec onglets

*Bugs rencontrés*
- Django 6 multiline `{# ... #}` comments rendus comme texte visible → fix : `{% comment %}{% endcomment %}` ou `{# single line #}`
- Ruff W605 invalid escape `\y` dans docstring → `ruff check --fix`
- djlint T002 single quotes dans template tag → remplacé par double quotes
- `account_badge.html` hardcode `whitespace-nowrap` → débordement nom compte → inliné avec `max-w-[90px] truncate`
- Layout 2 lignes rejeté → remplacé par 5 colonnes strictes (`flex-shrink-0` widths fixes)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Chips = compound keyword | Un seul keyword composé ("MIGROS CAROUGE"), pas N règles séparées | `_keyword_q()` AND natif, UX plus claire |
| "13 Migros" mystère | CIC 2023 = Grenoble FR (pas de Migros en France), CHF data seulement depuis 2024-2025 | Confirmé SQL — le parser est correct |
| Force flow | Check overwrite avant création, `force=1` skip le check | Évite d'écraser silencieusement des règles manuelles |

**Reste à faire (Phase 2G)**
- T3 : Créer catégorie depuis dropdown Créer (issue #34)
- T4 : `apply_rules` management command (issue #32)
- Session classification manuelle (~4h)
- Merge → development → main + tag v0.1.0

---

## 2026-05-06 — Session 21 : Audit import + fix computed_balance + merge fix/import-storage-ux (Cowork)

**Contexte**
Session de clôture de la branche `fix/import-storage-ux`. Audit complet du système d'import suivi du fix du bug critique `computed_balance` (import rétroactif). Merge et commit groupé de tout le travail Phase 2F storage + fix dans `feature/phase-2g-rules-crud`.

**Livré**

*Audit système d'import*
- 8 catégories de risques identifiées : 3 HIGH (computed_balance rétroactif, race condition session, /tmp orphans), 5 MEDIUM/LOW
- Verdict : système **solide** une fois le bug computed_balance corrigé

*Fix computed_balance (services.py:403)*
- Ajout `date__lt=snapshot_date` dans `BalanceSnapshot.objects.filter(account=account)` avant `.order_by("-date").first()`
- Sans ce filtre : import rétroactif → snapshot le plus récent pris comme base → valeur aberrante
- Commentaire explicatif ajouté dans le code

*Commit groupé `57e8005` (37 fichiers, 3639 insertions)*
- `imports/storage.py` — chiffrement Fernet + stockage fichiers importés
- `ImportLog` : champs `storage_path`, `storage_encrypted`, `storage_error`, `date_min`, `date_max`
- `Transaction.import_log` : `SET_NULL → CASCADE` (suppression log = suppression transactions)
- `Account.iban` : champ centralisé (migration 0011)
- Migrations 0008-0012 : storage, rehash CIC/UBS, date_range, cascade
- `signals.py` : gestion cascade suppression via pre_delete
- Templates : `_steps_already_imported.html`, `_steps_account_picker.html`, `_steps_result.html` amélioré
- Tests : `test_import_storage` (16 cas), `test_import_zero_tx`, `test_balance_snapshots`, `test_cascade_and_signals`, `test_hash_stability`
- Connecteurs refactorisés : `base.py`, `resolver.py`, CIC/UBS/Yuh (stabilité hash + IBAN)
- **171 tests passent**

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Import system "solide" | ✅ validé après fix computed_balance | Bug rétroactif était le seul risque de corruption données — les autres issues sont edge cases ou monitoring |
| Merge fix/import-storage-ux | → `feature/phase-2g-rules-crud` (pas main) | fix/ est une sous-branche de feature/phase-2g — merge logique dans le parent |

**Bugs résolus**
- `computed_balance` rétroactif → filtre `date__lt=snapshot_date` ajouté
- Base de test `test_bricbudget` verrouillée entre deux runs pytest → `DROP DATABASE` manuel
- Ruff/djlint reformatent à chaque commit → re-stage + nouveau commit (pattern connu)

**Reste à faire (Phase 2G)**
- T2 : Créer règle standalone depuis dropdown Créer (issue #33)
- T3 : Créer catégorie depuis dropdown Créer (issue #34)
- T4 : `apply_rules` management command (issue #32)
- Fermer issue #35 (import storage livré)
- Session classification manuelle (~4h)
- Merge → development → main + tag v0.1.0

---

## 2026-05-02 — Session 20 : Phase 2G T1 — CRUD règles de catégorisation (VSCode)

**Contexte**
Démarrage Phase 2G sur `feature/phase-2g-rules-crud`. Objectif T1 : UI CRUD complète pour les `CategorizationRule` accessible depuis le dropdown Paramètres → "Gérer les règles intelligentes".

**Livré**

*CRUD règles — backend*
- **`budget/views.py`** : 5 nouvelles vues + helper `_cats_with_subcats()` (2 requêtes sans N+1 via dict keyed by `category_id`)
- **`budget/urls.py`** : 5 nouvelles URLs (`panel/rules/`, `rules/<id>/toggle/`, `rules/<id>/delete/`, `rules/<id>/edit/`, `rules/<id>/edit/submit/`)

*CRUD règles — templates*
- **`_panel_rules_list.html`** : panel modal avec header + liste + état vide
- **`_rule_row.html`** : ligne lecture — icône catégorie/sous-cat (fond light `colour_hex+40`), actions hover (edit/toggle/delete)
- **`_rule_row_edit.html`** : formulaire inline — picker accordéon `<details>` inline (pas absolu) identique à `_cat_picker_row.html` : `ml-5`, `colour_hex+26` Principale, `colour_hex+66` sous-cats, `w-5` icônes, badge Principale bordé, chevron `›` rotatif, `group-open:text-gold`
- **JS `ruleEditSelect(isSubcat)`** : met à jour hidden inputs + icône summary (fond light si sous-cat)

*Dropdowns index.html*
- Dropdown **Créer** : w-56→w-80, icônes Finary (folder / sparkles / bullseye), labels "Nouvelle catégorie / Nouvelle règle intelligente / Nouvel objectif de dépense"
- Dropdown **Paramètres** : w-64→w-80, sparkles sur "Gérer les règles intelligentes", section Affichage supprimée

*Dev tooling*
- **`make lint`** : ruff check + djlint --lint
- **`make check`** : lint + pytest en un appel

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Picker inline `<details>` | Pas d'`absolute` positioning | L'absolute est clippé par `overflow-y-auto` du modal → picker inutilisable. Inline = le modal scroll naturellement. |
| `_cats_with_subcats()` helper | 2 requêtes (cat + subcat) via dict | Évite N+1 : une requête SubCategory avec `select_related`, un dict `{cat_id: [subs]}`, zip avec les cats. |
| Picker = layout identique `_cat_picker_row.html` | Cohérence visuelle | L'utilisateur connait déjà ce picker depuis le panel "Tout voir". Même apprentissage moteur. |

**Bugs rencontrés**
- `{# #}` multiligne rendu comme texte visible (régression connue QUESTIONS.md) → commentaire sur une seule ligne
- Dropdown absolu clippé par `overflow-y-auto` modal → inline `<details>` flow
- `<button>` a `text-align: center` par défaut navigateur → `text-left` obligatoire sur les boutons picker
- djlint/ruff-format reformatent à chaque commit → re-stage + nouveau commit

**Reste à faire (Phase 2G)**
- T2 : Créer règle standalone depuis dropdown Créer (issue #33, actuellement SOON)
- T3 : Créer catégorie depuis dropdown Créer (issue #34, actuellement SOON)
- T4 : `apply_rules` management command + `make apply-rules` (issue #32)
- Session classification manuelle (~4h)
- Merge → development → main + tag v0.1.0

---

## 2026-05-02 — Session 19 : Bug fixes — CHF partout + picker in-page + layout (VSCode)

**Contexte**
Session de polish sur `feature/phase-2f-import` : les montants s'affichaient en devise native au lieu de CHF, le picker catégorie était inopérant depuis `category_detail.html`, et le layout du panel droit était désaligné après ajout du scroll automatique.

**Livré**

*CHF partout*
- **`_panel_tx_row.html`** : montant colonne 4 → `amount_chf|default:tx.amount|chf_dec` (était `amount` brut)
- **`_panel_tx_detail.html`** : montant principal → CHF (3xl bold) + ligne "Montant EUR/GBP" séparée si devise ≠ CHF
- **`views.py` — 9 agrégats** : `Sum("amount")` → `Sum(Coalesce("amount_chf", "amount"))` — bug 1:1 EUR/CHF corrigé dans tous les KPIs, Sankey, Donut, historique

*Category picker depuis `category_detail.html`*
- **Pattern `source` + `detail_target`** : propagé à travers toute la chaîne HTMX (detail → picker → _cat_picker_row → POST → retour detail)
  - `source="category"` → `detail_target="#cat-tx-detail"` (div fixe in-page)
  - `source=""` → `detail_target="#panel-content"` (overlay flottant)
- **`budget_panel_tx_detail()`** : expose `source` et `detail_target` au template
- **`budget_panel_category_picker()`** : idem + forwarding aux rows
- **`budget_categorize_transaction()`** : `hx_trigger` calculé avant le `if source` branch → toast envoyé dans **les deux** branches (était manquant sur `source=category`)
- **`_panel_category_picker.html`** : bouton × et ← contextuels (retour vers `#cat-tx-detail` ou `#panel-content`)
- **`_cat_picker_row.html`** : `hx-target="{{ detail_target|default:'#panel-content' }}"` sur les deux forms

*Layout + UI polish*
- **`_panel_tx_row.html`** : `hx-on::after-request="scrollIntoView()"` quand `panel_target` défini — scroll automatique vers `#cat-tx-detail` après chargement
- **`category_detail.html`** : `sticky top-4 self-start` supprimé des deux `<aside>` panel_right — le sticky + `overflow-y-auto` + `p-4` créait un décalage vertical de ~16px au premier rendu
- **`category_detail.html`** : `overflow-hidden` sur `#cashflow-card` — le `border-b` du tab strip ne dépasse plus des coins `rounded-xl`
- **Bouton "+" Objectif** : `w-8 h-8` → `w-6 h-6`, SVG `w-3.5` → `w-3` — aligné avec le texte des autres tabs

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `sticky` supprimé | scrollIntoView à la place | `sticky top: 16px` dans container `overflow-y-auto` avec `p-4` = artifact rendering : l'élément se positionne par rapport au viewport, pas au flex-start. Impossible à corriger proprement avec du CSS. |
| `hx_trigger` avant `if source` | Une seule construction | Les deux branches (category + list) doivent envoyer le toast. Extract-before-branch évite la duplication. |
| Native currency row conditionnelle | `if tx.currency != "CHF"` | CHF natif = pas de doublon. EUR/GBP = on garde la traçabilité bancaire (montant original visible). |

**Bugs rencontrés**
- Toast absent sur `source=category` → `hx_trigger` construit APRÈS le `if source` dans l'original → ne rentrait jamais dans la branche `category` avec la valeur. Fix : extract avant le `if`.
- Pre-commit hook ruff-format + djLint reformate les templates → commit échoue → re-stage des fichiers reformatés → nouveau commit.
- Sticky misalignment : 3 tentatives de correction par spacer (`h-8 → h-7 → h-8`) avant de comprendre la cause racine (sticky + overflow-y-auto).

**Merge**
- Commit `5f2e5c5` sur `feature/phase-2f-import`
- Merge `development` ← `feature/phase-2f-import` (commit `15960af`)
- PR #28 reste ouverte — critères main pas encore tous remplis (export règles)

---

## 2026-05-01 — Session 18 : Phase 2F polish — graphique Activité + bank_logo (VSCode)

**Contexte**
Suite directe de la Phase 2F : redesign complet de la page import avec un vrai graphique ECharts, et unification de l'affichage des logos banques via un template tag + composant partagés.

**Livré**

*Page Import — redesign Activité*
- **Layout** : Activité (hero gauche, `flex-[2]`) + Historique (table CSS grid) / Importer + Synchronisation (droite, `flex-[1]`)
- **`static/js/charts/activity.js`** : `BricCharts.initActivity(el, data)` — bar chart empilé par banque, buckets jour (1M) ou semaine (3M/1A), labels début de mois pour vue semaines
- **Boutons 1M/3M/1A + Nouvelles/Total** : style identique Sankey `period_nav.html` (`w-8 h-8 rounded-full`, actif `text-gold bg-gold/15`)
- **`base_app.html`** : `{% block panels_align %}` — override flex alignment par page
- **Historique** : une ligne par ImportLog (CSS grid 8 colonnes), badges IBAN/RIB/CONV avec tooltip
- **Synchronisation** : groupée par banque, pastille statut ok/recent/stale/never

*Logos banques — abstraction partagée*
- **`transactions/templatetags/bank_icons.py`** : tag `{% bank_icon_url bank_or_slug %}` — SVG priorité, PNG miniature fallback, initiale si vide
- **`components/banks/bank_logo.html`** : cercle icône réutilisable — SVG = `bg-surface-3` + `brightness-0 invert`, PNG = `bg-white`
- **`upload.html`** : remplace logos inline `bg-surface-hover` + `.png` hardcodé par le composant (Historique + Synchronisation)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `{% bank_icon_url %}` template tag vs Python batch | Tag pour volume faible (imports page) | Volume < 10 banques — pas besoin du batch `_resolve_bank_icon_map()`. Budget garde le batch Python pour les listes longues. |
| `bank_logo.html` séparé de `account_badge.html` | Composants distincts | `bank_logo` = icône seule. `account_badge` = icône + nom compte. Évite surcharge sur template nesting pour listes transactions. |

**Bugs rencontrés**
- Template tag `bank_icons` non découvert → serveur Django démarré avant création du fichier → cache non rechargé → `TemplateSyntaxError`. Fix : restart serveur. **Règle** : ne jamais committer sans tester en navigateur.
- `_icon_url` variable Django refusée (variables ne peuvent pas commencer par `_`) → renommée `bicon`
- `replace_all` sur `_icon_url` a mangé le nom du tag `bank_icon_url` → `bankicon` → correction manuelle

**Reste à faire**
- Phase 2G : session classification (~4h) → 0 transaction "Non catégorisé" sur 12 mois
- Export `CategorizationRule` en JSON (QUESTIONS.md) — prérequis avant classification
- Merge `feature/phase-2f-import` → `main` (critères QUESTIONS.md)

---

## 2026-04-30 — Session 17 : Phase 2F complète — import UI + bug fixes (VSCode)

**Contexte**
Finalisation de la Phase 2F (Import CSV UI) : flow complet upload → dry-run → confirm fonctionnel pour Yuh, UBS et CIC multi-feuilles. Deux sessions de corrections intensives (création de comptes inline, gestion des IBAN, bugs parseurs).

**Livré**

*Infrastructure comptes*
- **`banks_config.py`** : config hardcodée des banques connues (Yuh, UBS, CIC, Boursorama, Finpension) — pas de .env
- **`seed_banks`** : commande idempotente `update_or_create` depuis `banks_config.py`
- **`seed_accounts`** : wizard interactif `getpass` pour IBAN/RIB sensibles (pas de .env)
- **`seed_categories`** : commande isolée qui ne touche que catégories/sous-catégories — sans recréer banques/comptes
- **`CheckingAccount.iban` nullable** : `unique=True, null=True` — SQL NULL ≠ NULL → plusieurs NULL autorisés
- **`Account.Currency` choices** : CHF, EUR, GBP, USD comme `TextChoices`
- **Migrations** : 0008 (Currency choices), 0009 (iban deprecated), 0010 (iban nullable)

*Import flow*
- **`_account_file_hash(file_hash, sheet_name)`** : hash dérivé SHA256 par feuille CIC → évite IntegrityError ImportLog
- **`ImportLog.file_hash` max_length=64** : SHA256 = 64 chars (était 40) + migration 0007
- **`seen_in_batch` set** : dédup intra-fichier avant `bulk_create` (cas UBS doublons)
- **Catégories par défaut** : `revenus` (amount ≥ 0) / `inconnu` (amount < 0) si aucune règle ne matche
- **`_steps_result.html`** : compteur `+N` et `N déjà importé` par ligne de compte
- **`_steps_create_account.html`** : fragment inline si `AccountNotFound` (banque pré-remplie)
- **`import_create_account` view** : création Account + CheckingAccount/SavingsAccount, relance dry-run

*Fixes parseurs*
- **UBS savings** : `matches_file` scan dynamique lignes 3-12 (variante 8-ligne metadata)
- **UBS** : `description2` inclus dans hash, `extract_account_name()` lit ligne 1
- **CIC** : appel `connector.parse_sheet(tmp_path, match.sheet_name)` direct (plus de `parse(**kwargs)`)
- **`resolver.py` Yuh** : `get()` → `first()` + `order_by("-id")` — évite `MultipleObjectsReturned` si plusieurs comptes Yuh actifs
- **`Category` import manquant** dans `services.py` → `NameError: name 'Category' is not defined`
- **`float * Decimal`** dans le fallback catégorie : `amount = float(...)` → `amount = Decimal(str(...))` — cassait 100% des imports CIC (EUR) et tout import avec taux de change

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| IBAN/RIB en wizard `getpass` | Pas de .env pour les comptes | User refuse le .env — données sensibles saisies interactivement une fois |
| `CheckingAccount.iban` nullable | `unique=True, null=True` | Yuh et Finpension n'ont pas d'IBAN extractible du fichier |
| `seed_categories` isolé | Séparé de `seed_initial` | `seed_initial` recréait de mauvais comptes/banques — commande dédiée sans effet de bord |
| Resolver Yuh `first()` | Au lieu de `get()` | Si doublon de compte Yuh actif (wizard + existant), `get()` crash. `first()` prend le plus récent. |

**Bugs rencontrés**
- `NameError: name 'Category' is not defined` dans `services.py` → import manquant → `from transactions.models import Category, ...`
- `float * Decimal` crash sur tous les imports CIC (EUR) et UBS (CHF → taux de change) → `amount = Decimal(str(tx.get("amount", 0)))` dans le bloc fallback catégorie
- `MultipleObjectsReturned` sur Yuh → doublon compte C/C id=146 désactivé manuellement + resolver passe à `first()`
- `IntegrityError` sur ImportLog CIC multi-feuilles → même `file_hash` pour 3 feuilles → `_account_file_hash()` dérive un hash unique par (file, sheet)
- `value too long for type character varying(40)` sur `ImportLog.file_hash` → SHA256 = 64 chars → migration max_length=64

**Reste à faire**
- Phase 2G : session classification (~4h) → 0 transaction "Non catégorisé" sur 12 mois
- Export des règles de catégorisation avant la classification (QUESTIONS.md)
- Merge `feature/phase-2f-import` → `main` (critères QUESTIONS.md)

---

## 2026-04-29 — Session 15 : resolver + dual balance + docs (VSCode)

**Contexte**
Pré-requis techniques avant Phase 2F : centralisation de la détection banque/compte dans un module partagé, robustification du calcul de solde, et mise à jour complète de la documentation DB.

**Livré**
- **`connectors/resolver.py`** (nouveau) : `detect_connector(filepath)` → premier connecteur qui matche. `resolve_accounts(connector, filepath)` → `list[AccountMatch]` — logique Yuh (convention slug), UBS (IBAN contract_number), CIC (RIB par feuille). Remplace les 3 `_find_account()` éparpillés dans les commandes.
- **`BalanceSnapshot`** : `balance` rendu nullable + `computed_balance` ajouté (prev_snapshot + sum new tx) + propriétés Python `authoritative_balance` (balance ?? computed) et `drift` (écart) + migration `0007_balancesnapshot_computed_balance_and_more`.
- **`ImportService`** : toujours créer le snapshot même si `balance=None`, calcule `computed_balance`, log warning si dérive > 0.01.
- **Commandes refactorées** : `import_yuh`, `import_ubs`, `import_cic`, `import_all` utilisent le resolver — `_find_account()` supprimé partout.
- **Tests** : `test_account_resolution.py` réécrit pour tester `resolve_accounts()` directement — 88/88.
- **`documentation/schema_db_v2.mermaid`** : `computed_balance` documenté, 3 guides inline (ajouter banque / compte / carte).
- **`documentation/import_system.md`** : réécriture partielle — resolver, dual balance, 3 guides d'extension, état d'avancement corrigé (CIC ✅).

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `resolver.py` dans `connectors/` | Module Python pur, pas une app Django | Appelable depuis commandes ET vues sans dépendances Django management |
| `resolve_accounts` retourne toujours une liste | Même pour Yuh (1 élément) | Le caller (vue Phase 2F) itère uniformément sans cas particulier |
| `balance` nullable sur `BalanceSnapshot` | Oui | Yuh URL-encode le nom de fichier → extraction peut échouer → on crée quand même le snapshot avec `computed_balance` |
| Drift stocké en propriété Python | Non stocké en DB | Calculable à la volée, évite une colonne redondante. Si besoin de filtrer les dérives → ajouter la colonne plus tard |

**Bugs rencontrés**
- Tests `test_account_resolution.py` en erreur après suppression `_find_account()` → cause : 7 tests appelaient `cmd._find_account()` directement → fix : réécriture pour tester `resolve_accounts()` du resolver

**Reste à faire**
- Phase 2F : `git checkout -b feature/phase-2f-import` + scaffold app `imports/`

---

## 2026-04-28 — Session 14 : category_detail polish — panel fixe + badge fix + alignement (VSCode)

**Contexte**
Session UI sur `category_detail.html` : finalisation du panneau de détail transaction en div fixe (pas overlay), correction du badge "Règle intelligente" qui s'affichait sur toutes les transactions, et alignement visuel Cashflow ↔ Distribution.

**Livré**
- **`panel_target` dans `_panel_tx_row.html`** : variable de contexte optionnelle. Si définie, `hx-target` pointe vers un div fixe (ex: `#cat-tx-detail`) au lieu de `#panel-content`, et `openPanel()` n'est pas appelé. Rétro-compatible (défaut = overlay).
- **`#cat-tx-detail` dans `category_detail.html`** : div fixe sous le donut Distribution (panel_right). Affiche le détail de la transaction au clic, sans ouvrir l'overlay. Placeholder "Cliquez sur une transaction" si vide.
- **`close_on_back=True`** dans `budget_panel_tx_detail()` quand `source=category` : le bouton ← ferme le panel overlay au lieu de recharger la liste, cohérent avec le contexte (liste déjà visible à gauche).
- **Badge "Règle intelligente appliquée" corrigé** : n'apparaît plus que pour `categorization_source="rule"`. Avant : s'affichait aussi pour `"ai"`, ce qui touchait 3 873/3 902 transactions (toutes catégorisées par un script dev).
- **Alignement Cashflow ↔ Donut** : `id="cashflow-card"` + `id="donut-card"`, JS post-init qui lit `offsetHeight` du cashflow et l'applique en `minHeight` sur le donut. Les deux cards ont désormais la même hauteur → `#cat-tx-detail` s'aligne naturellement avec la liste des transactions.
- **Refactoring aside panel_right** : `flex flex-col gap-4` remplace le pattern `h-8 mb-4` — espacement identique, mais compatible avec le layout multi-enfants (spacer + donut + détail).

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `panel_target` optionnel | Variable de contexte dans `_panel_tx_row.html` | Évite de dupliquer le fragment pour les deux cas (overlay vs div fixe) — un seul template, deux modes |
| Badge `categorization_source` | Badge = "rule" seulement | "ai" = Phase 6 non implémentée. Les 3 873 tx "ai" viennent d'un script dev, pas de l'IA réelle |
| Alignement hauteur | JS `offsetHeight` après init charts | ECharts fixe les hauteurs des containers en CSS → mesure stable, pas besoin de polling |
| `sticky top-4` retiré | Causait un décalage vertical de 16px au chargement | Dans un container `overflow-y: auto`, `position: sticky; top: 16px` pousse l'élément vers le bas à scroll=0 si sa position naturelle est à 0px du content-edge |

**Bugs rencontrés**
- Badge "Règle intelligente" sur toutes les transactions → cause : `categorization_source='ai'` sur 3 873 tx (script `dev subcategory assign` du commit `b91f2d5`) — fix : condition `== "rule"` uniquement
- Décalage vertical 16px après ajout `sticky top-4` → cause : sticky pousse l'élément de `top` pixels en dessous de sa position naturelle dans un scroll container → fix : retrait de `sticky top-4`

**Reste à faire**
- Phase 2F : branche `feature/phase-2f-import` + scaffold app imports + upload HTMX

---

## 2026-04-28 — Session 13 : UX + Plan Phase 2F — Page Import

**Contexte**
Session de design et planification (pas de code). Conception complète de la page `/import/` avec UX inspirée Finary. Plan d'action écrit et sauvegardé dans `.claude/plans/`.

**Livré**
- **UX Import décidée** : layout Finary (liste groupée par date + panel droit au clic) — même pattern que Patrimoine > Transactions
- **Flow progressif** : 4 étapes avec CSS `animation-delay` (0 / 350 / 700 / 1050ms) — pas de WebSocket ni polling
- **Plan complet** sauvegardé dans `.claude/plans/excellent-prends-des-bright-sparkle.md` — réutilisable à chaque session
- **Décision merge `main`** : attendre Phase 2F complète (question QUESTIONS.md fermée → 🟢)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Layout import | Liste groupée par date + panel droit (pattern Finary transactions) | Cohérence avec le reste de l'app — pas une page "wizard" isolée |
| Progressive reveal | CSS animation-delay, pas HTMX polling | Plus simple, plus fiable, même effet visuel |
| Double entrée | Sidebar "Importer" + icône `↑` topbar | Deux contextes d'usage : navigation normale + action rapide |
| Architecture | App `src/imports/` sans modèle propre | Lit `ImportLog` et appelle `ImportService` existants — zéro nouvelle DB |
| Watcher | Section SOON en bas de page | Infrastructure background (Django-Q) hors scope Phase 2F |
| Merge main | Après Phase 2F complète | Utilisation réelle nécessite l'import UI + export rules |

**Prochaine session**
- Créer branche `feature/phase-2f-import`
- Coder Session 1 du plan : scaffold app + page liste + upload bar

---

## 2026-04-28 — Session 12 : Homogénisation parseurs + re-import complet (VSCode)

---

## 2026-04-25 — /audit : Phase 2C terminée (rapport `.claude/audits/2026-04-25.md`)

**Résumé des findings :**
- 🔴 **[SEC-01] IDOR** : transactions non isolées par user (`get_object_or_404` sans filtre user) — bloquant avant Phase 3 (Carys), acceptable mono-user
- 🟠 **[SEC-02] GET mutation session** : `budget_set_period`, `set_tab`, `set_cat_tab`, `set_period_month` changent la session via GET (pas POST) — faible impact, UI state seulement
- 🟠 **[SEC-03] `budget_modal_target_create`** sans `@require_POST` — fonctionnel mais non conforme convention Django
- 🟡 **[SEC-04] SHA1 `import_hash`** — ✅ **résolu session 12** (SHA256 + migration 0005)
- 🟡 **[SEC-05] `urlretrieve` sans validation scheme** — SSRF théorique, URL admin seulement
- 🟡 **[SEC-06] 5 warnings Django deploy check** — tous acceptables en dev, bloquants prod (Phase 2G)
- 🟡 **[PERF-01]** Index manquants sur champs filtrés

**Actions résolues depuis :** SEC-04 (SHA256) ✅

---

**Contexte**
Session de refactoring qualité sur les connecteurs. L'utilisateur a demandé un re-import "brut de fonderie" avec des parseurs fiables et cohérents entre CIC, YUH et UBS. Flush complet + re-import de 3902 transactions.

**Livré**
- **Homogénisation SHA1→SHA256** : tous les parseurs utilisent SHA256 pour `import_hash`. Migration Django `0005_import_hash_sha256` : `max_length` 40→64 sur `Transaction.import_hash`. Les anciens hashes SHA1 (40 chars) sont désormais invalides → flush nécessaire et fait.
- **`BaseConnector._normalize_merchant()`** : méthode partagée dans `base.py` — collapse spaces + title-case. Chaque `_clean_merchant()` l'appelle comme étape finale. Garantit un rendu uniforme quelle que soit la banque.
- **UBS `import re` module-level** : `import re` était à l'intérieur de `_clean_merchant()` — déplacé au niveau du module (bonne pratique Python, ruff l'avait signalé).
- **Flush + re-import complet** : 3902 tx + 5 ImportLog flushés, re-import propre avec `make import-all COMMIT=1`. Résultat : 3902 tx créées, 0 erreurs.
- **88 tests passants** après migration.

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| SHA1 → SHA256 | Migration forcée + re-import complet | SHA1 est deprecié (ruff S324), hashes incompatibles entre ancienne et nouvelle version → flush propre plutôt que migration partielle |
| `_normalize_merchant` dans BaseConnector | Méthode partagée, pas un module utilitaire séparé | Cohérence sans over-engineering : chaque connecteur garde sa logique spécifique, seule la finalisation (collapse + title-case) est mutualisée |
| Re-import "comme des bourrins" | Flush complet (tx + ImportLog) puis re-import total | Simplifié : pas de migration partielle, pas de mise à jour sélective. État propre garanti. |

**Bugs rencontrés**
- `import_hash varchar(40)` rejetait SHA256 (64 chars) → `DataError: value too long` au premier test — fix immédiat via migration `0005`
- ImportLog file_hash bloquait le re-import (déduplication fichier déjà importé) → flush ImportLog nécessaire avant re-import

**Reste à faire**
- Phase 2F : app `src/imports/` + flow upload HTMX + mini KPI dashboard

---

## 2026-04-28 — Session 11 : Analyse UX + planification phases 2F / 3A

**Contexte**
Session de stratégie et planification (pas de code). Analyse des 11 nouveaux screenshots Finary (Patrimoine > Comptes bancaires). Challenges au prompt initial, décisions d'architecture.

**Livré**
- **11 screenshots renommés** dans `assets/private/references/finary_layout/` — convention `patrimoine-vue-etat.png`
- **`documentation/ui_patrimoine_specs.md`** créé — specs complètes UX Patrimoine/Comptes bancaires (navigation, pages, filtres, réutilisation partials)
- **TASKS.md mis à jour** — Phase 2F détaillée, Phase 3A Patrimoine créée, Synthèse → SKIP Phase 4
- **Mémoire persistante** : convention renommage macOS NFD + plan phases 2F/3A

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Synthèse | SKIP Phase 4 | Synthèse Finary = Patrimoine brut (ETFs + Finpension). Données inexistantes avant Phase 4. |
| Import entry | Topbar icône [↑] + sidebar item | Double point d'entrée voulu par Emmanuel |
| Ordre phases | Import d'abord (2F) → Patrimoine (3A) → Sous-cats (2D) | Import = déblocant terrain (utilisation réelle) |
| `import_all.py` | Commiter + intégrer dans Phase 2F | Commande propre et terminée, scan dossier + orchestration banques |
| Architecture | Nouvelle app `src/imports/` + `src/patrimoine/` | Séparation responsabilités, même pattern que `budget/` |
| Watcher | SOON badge Phase 6 | Infrastructure background (Django-Q) hors scope Phase 2F |
| Screenshots macOS | Python `os.rename()` + NFD | `mv` bash échoue sur caractères NFD macOS (é, à, ') |

**Prochaine session**
1. Commit 4 fichiers modifiés + `import_all.py`
2. Re-import CIC (merchant_name cassés)
3. Phase 2F : app `src/imports/` + upload flow HTMX + mini KPI dashboard

---

## 2026-04-24 — Phase 2C (session 5) : Tab Objectif complet — bar chart + gauge SVG réutilisable (VSCode)

**Contexte**
Deuxième session du jour. Redesign complet du tab "Objectif" dans `category_detail.html` : bar chart 12 mois cliquable à gauche, gauge semi-cercle + KPIs à droite. Refactoring de la gauge SVG en composant réutilisable utilisé en 5 endroits.

**Livré**
- **`bar.js`** — `BricCharts.initBar()` : barres pilules (`borderRadius: [999]`), `barMaxWidth: 7`, y-axis gauche format compact (`1.5k`), zero line via `markLine`, ligne objectif pointillée avec `endLabel: "OBJECTIF"`, couleur active = `cat_color`, inactive = `applyFactor(cat_color, 0.3)`, clic = navigation vers ce mois
- **`budget_set_period_month`** — vue `GET /budget/period/month/<year>/<month>/` : écrit `budget_period_mode = "1m"` + `period_start/end` en session, redirige vers `HTTP_REFERER`. Pattern PRG identique à `budget_set_period`.
- **`monthly_history`** dans `budget_category_detail()` — 12 mois glissants, `TruncMonth + Sum`, labels courts sans année (`"Avr"`, `"Mai"`, ...), `history_chart_data` JSON injecté via `json_script`
- **`_gauge.html`** — composant SVG réutilisable : `<circle cx="50" cy="50" r="40">` plein + `stroke-dasharray` + `rotate(180, 50, 50)`. ViewBox `"0 0 100 52"` clippe les oreilles nativement (SVG `overflow:hidden`). Params : `gauge_fill_px`, `gauge_color`, `gauge_class` (défaut `w-16`)
- **Filtres `gauge_fill` + `gauge_color`** dans `budget_filters.py` : `GAUGE_HALF_PERIMETER = 125.66` (π×40), couleurs depuis tokens Tailwind
- **Tab Objectif `panel_left`** : card "HISTORIQUE MENSUEL" + `#bar-chart` div + état vide "Aucune donnée"
- **Tab Objectif `panel_right`** : card "Objectif" avec spacer alignement + grande gauge `w-44` + 3 KPIs row (Dépenses / Restant / Objectif mensuel)
- **5 usages de `_gauge.html`** : grande gauge panel right + mini `w-8` tab strip + Col1L2 `% Dépenses` + Col3L1 `% Dépenses année` + Col3L2 `Dépassement objectif`
- **KPI grid 3 colonnes égales** — `grid-cols-3 gap-2`, headers Finary-style blanc uppercase (`tracking-widest`)
- **Nettoyage tab strip** : point orange supprimé, bouton stylo supprimé
- **Alignement panel right** : spacer invisible `h-8 mb-4` pour aligner la card avec la row cashflow gauche

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Gauge SVG — technique | `<circle>` + `stroke-dasharray` + `rotate(180)` | Path + `stroke-linecap: round` crée des oreilles en dehors du viewBox — le cercle complet avec dasharray n'a pas ce problème. ViewBox 100×52 clippe les extrémités. |
| Clic barre → full redirect | `budget_set_period_month` + redirect HTTP_REFERER | Partial HTMX (spec initiale) trop complexe pour le gain UX. La page entière se met à jour avec le bon mois — comportement identique. |
| Labels mois sans année | `MOIS_FR[m.month][:3]` seulement | "Avr 2025" → "Avr" : moins de bruit visuel sur un bar chart 12 mois. L'année est implicite (12 derniers mois). |
| Couleur barre inactive | `applyFactor(cat_color, 0.3)` | Cohérence avec le style donut/sankey (palette monochrome). Pas de hex hardcodé. |

**Bugs rencontrés**
- Gauge "oreilles" (ear/horn bug) : `<path>` arc + `stroke-linecap: round` → caps semicirculaires aux extrémités sortent du viewBox → visible. Fix : `<circle>` plein + dasharray. Les caps sont toujours là mais pointent vers y=50+r (bas du cercle) → clippés par viewBox 52px.
- Y-axis trop décalé à droite : `grid.left: "10%"` → remplacé par `grid.left: 0` + `containLabel: true`.
- Labels mois superposés : `interval: 0` force l'affichage de tous les labels — ok avec 12 mois + font 9px.

**Reste à faire**
- Re-import CIC (merchant_name update — parser fixé le 2026-04-23)
- Deuxième passe icônes catégories

---

## 2026-04-24 — Phase 2B (session 4) : KPI tabs + cercles SVG + polish sidebar + Sankey no-income (VSCode)

**Contexte**
Session de finition Phase 2B : les 3 dernières tâches du plan (KPI tabs, cercles progression, re-import CIC) + plusieurs corrections UX découvertes en testant avec données réelles d'avril 2026.

**Livré**
- **KPI tabs `category_detail.html`** : les 3 KPIs (`[Transactions] [Sous-catégories] [Objectif]`) deviennent des `<a>` cliquables via `budget:set_cat_tab`. Active = `border-b-2 border-gold + text-gold`. Contenu conditionnel : tab "subcategories" → liste avec icônes, autres tabs → liste transactions
- **Icônes sous-catégories** dans l'onglet Sous-catégories : cercle `w-8 h-8` couleur catégorie 40% + SVG `brightness-0 invert`
- **Sankey font size** : 10 → 8px
- **Cercles SVG de progression** autour des icônes catégories sur `index.html` : arc `stroke-width: 3.5`, couleur de la catégorie, gap visuel via outer `w-10 h-10` + inner `w-7 h-7`. Budget text sous le nom : vert `target_raw_pct%` ou orange `+X CHF au-dessus` (token `warning: #f97316` ajouté dans `base.html`)
- **Enrichissement `budget_index()`** : `target_pct`, `target_raw_pct`, `target_overspend_chf` calculés pour chaque catégorie depuis `BudgetTarget` × `period_months`
- **Soon badges homogénéisés** : tous les badges hardcodés remplacés par `{% include "components/badges/soon.html" with extra_class="..." %}` — `index.html` (4 badges), `sidebar.html` (Comptes), `base_app.html` (topbar)
- **DEV labels supprimés** de `base_app.html` : sidebar.html, topbar, `[ objectifs du mois ]`, panel_left·panel_right, right_panel.html
- **Sidebar UX** : `border-b` logo supprimé, `border-t` séparateur avant Paramètres supprimé, Paramètres déplacé hors `<nav>` → ancré en bas juste au-dessus du profil
- **Borders layout** : `border-r border-edge` sidebar + `border-b border-edge` topbar supprimés dans `base_app.html`
- **Changement de mode période** : ancre sur aujourd'hui comme fin (le plus récent), plus maintien du vieux `period_start`
- **Sankey no-income** : séparation des boucles `income→pool` / `pool→expense` dans `views.py` (étaient gated par `if income AND expense`). JS injecte `__no_income__` fantôme invisible + ECharts `graphic` "Pas de revenu sur cette période". Tooltip HIDDEN_NODES → vide

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Changement mode période | Toujours ancrer sur aujourd'hui comme FIN | UX : naviguer entre 1M/3M ne doit pas bloquer sur un vieux mois |
| Token `warning: #f97316` | Nouveau token orange distinct de `expense` (rouge) | Rouge = dépassement critique, orange = avertissement budget — sémantique différente |
| Sankey no-income | Nœud fantôme `__no_income__` invisible + graphic text | ECharts Sankey ne peut pas rendre sans flux entrant — le fantôme préserve le layout |
| Links séparés dans view | Séparer boucles income/expense dans sankey data | `if income AND expense` bloquait les liens pool→expense quand income=0 — root cause du chart blanc |

**Bugs rencontrés**
- Sankey blanc en avril 2026 : `if income_categories and expense_categories` gating les liens pool→expense → aucun lien construit → `totalOut=0` → fantôme JS non injecté → chart vide
- `color: "transparent"` invalide dans ECharts itemStyle → `rgba(0,0,0,0)` requis
- Label `__no_income__` visible (5604 CHF) → `label: { show: false }` manquant dans le nœud fantôme
- Tooltip exposait `__no_income__ → __pool__` → filtre via `HIDDEN_NODES.has(source/target)`

**Reste à faire**
- Re-import CIC (merchant_name update — parser déjà fixé le 2026-04-23)
- Tab Objectif : gauge semi-cercle (Phase 2C)
- Deuxième passe icônes catégories

---

## 2026-04-23 — Phase 2B (session 3) : BudgetTarget CRUD + wizard règle fixes + UX polish (VSCode)

**Contexte**
Session dense de debug et polish avec données réelles. Objectifs : (1) rendre le CRUD objectifs mensuels opérationnel de bout en bout, (2) corriger le wizard règles cassé sur données CIC réelles, (3) améliorer l'UX du category picker.

**Livré**
- **BudgetTarget → OneToOneField** : suppression du champ `period`, objectif mensuel global par catégorie. Migration avec `deduplicate_budget_targets` RunPython pour gérer les doublons
- **CRUD BudgetTarget** : bouton crayon sur KPI catégorie (circle border), modal liste toutes les catégories avec statut objectif, formulaire pré-rempli si existant, navigation ← retour vers liste
- **Dropdown "Créer" activé** : index.html — menu gold stylé, "Objectif mensuel" actif + "Catégorie" Soon
- **CIC parser fix** : `_clean_merchant` strip trailing code alphanumérique avec chiffre (`ESSOF108`, `B560945` supprimés)
- **`_keyword_q()` helper** : requête `iregex` avec `\y` word boundaries PostgreSQL — "ESSO" ne matche plus "ESSOF108"
- **Filtre tokens digit** : `not re.search(r"\d", t)` exclut les codes locaux des chips et suggestion initiale
- **Filtre "PAIEMENT"** : `budget_categorize_transaction` applique le même filtre noise que le wizard — plus "2562 transactions impactées"
- **Live preview → `htmx.ajax()`** : abandon `hx-trigger` custom events (unreliable sur modal-injecté) → `htmx.ajax()` direct avec `data-*` attributes
- **Submit disabled** si aucun keyword + guard 400 côté serveur
- **Category picker** : titre transaction blanc + bouton × doré sur même ligne, badge sous-catégorie (fallback catégorie)
- **Right panel** : × supprimé du shell (`right_panel.html`), chaque fragment gère son propre close
- **`bb-scroll` CSS** : thin scrollbar WebKit dans `base.html`
- **Rule preview** : liste scrollable complète (plus de "et X autres"), `merchant_name` affiché
- **Overspend** : `text-gold` → `text-expense` (orange-rouge Finary)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| BudgetTarget sans period | `OneToOneField(Category)` uniquement | L'objectif est un réglage permanent de catégorie, pas une cible par mois |
| `icontains` → `\y` regex | `iregex` + `\yWORD\y` word boundaries | "ESSO" matchait "ESSOF108" par substring — word boundary résout le faux positif |
| `htmx.ajax()` direct | Remplace `hx-trigger` custom events | Custom events unreliables sur DOM injecté dans modal — `htmx.ajax()` est toujours fiable |
| Panel × dans fragments | Chaque fragment gère son propre close | Shell × fermait le panel même sur contenu non pertinent |

**Bugs rencontrés**
- CSRF 403 sur POST BudgetTarget → `{% csrf_token %}` manquant dans le form → ajouté
- UniqueViolation à la migration → doublons BudgetTarget existants → `deduplicate_budget_targets` RunPython
- Admin crash après migration → `list_display`/`date_hierarchy`/`ordering` référençaient `period` → nettoyé
- "PAIEMENT" extrait comme keyword → toutes les tx CIC "impactées" → filtre noise appliqué dans `budget_categorize_transaction`
- Bouton crayon invisible → `text-text-disabled` quasi transparent → circle border + `text-text-muted`
- Chips bloquées sur première sélection → `htmx.trigger()` custom event unreliable → remplacé par `htmx.ajax()` direct

**Reste à faire**
- Cercles de progression SVG arc autour icônes catégories (objectif mensuel)
- KPIs comme onglets sélecteurs (`[Montant] [Transactions] [Objectif]`)
- Re-import CIC pour mettre à jour `merchant_name` des transactions existantes

---

## 2026-04-22 — Phase 2B (suite) : Sankey fixes + category detail polish + Soon badges (VSCode)

**Contexte**
Session de polish visuel après le refactoring JS. Import de données réelles (Yuh) → Sankey en mauvaise forme → série de fixes. Puis alignement Finary sur la page catégorie (donut panel droit, KPI strip, navigation période, palette monochrome). Désactivation des boutons non-fonctionnels avec badge Soon.

**Livré**
- **Import données réelles** : seed Yuh + UBS + CIC via ImportLog flush + re-import CSV
- **Sankey global — shape fix** : `layoutIterations: 0` désactive l'algo de réduction de croisements ECharts → income en haut, expense en bas, ordre exact du tableau `data`
- **Nœud `__disponible__`** : nœud invisible `rgba(0,0,0,0)` ajouté si revenus > dépenses → pool équilibré, pas de hauteur en trop, forme propre. Lien `opacity:0` skippé dans le gradient JS
- **Labels Sankey universels** : remplacement de la logique `hasPool` par `HIDDEN_NODES` set — source→RIGHT, target→LEFT quelle que soit la variante (global, catégorie, sous-catégories)
- **Gradient links** : couleur target node (pas source) — skip `__disponible__`
- **Palette monochrome** : `_seg_factor(i, n)` 0.70→0.35 (plancher min visible dark bg). `subcat_colors` partagé Sankey + Donut
- **Donut + liste sous-catégories** dans `panel_right` de `category_detail.html`
- **KPI strip 3-col** sous Sankey catégorie : Total · Transactions · Moyenne/tx
- **Navigation période** sur page catégorie : `period_nav.html` réutilisé + `set_period` redirect HTTP_REFERER
- **Animation Sankey** : 400ms `cubicOut` — défini au niveau root ET series (ECharts quirk Sankey)
- **Soon badges** : boutons filtres, sous-catégories, dropdowns, copy/expand dans `index.html` + "Compléter mon patrimoine" dans `base_app.html`

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `layoutIterations: 0` | Désactive réduction croisements ECharts | Avec 2 income + 13 expense, l'algo place income en bas → tout croisé. Ordre manuel = résultat correct |
| `__disponible__` invisible | Nœud rgba(0,0,0,0) + lien opacity:0 | Pool déséquilibré = hauteur Sankey bizarre. Le nœud invisible absorbe le surplus sans être visible |
| Palette monochrome | `_seg_factor` 0.70→0.35, même liste Sankey+Donut | "The sankey is uni color" — une couleur de base (category), n niveaux de luminosité pour les sous-cats |
| `_seg_factor` plancher 0.35 | Plancher relevé de 0.15 à 0.35 | 0.15 = trop sombre sur fond dark, sous-catégories invisibles |
| animation root+series | `animationDuration` dans series ET root | ECharts Sankey ignore parfois le level root seul — les deux garantissent que ça prend |
| HTTP_REFERER redirect | `set_period` utilise REFERER ou fallback index | Même URL `set_period` fonctionne depuis toutes les pages sans URL dédiée |

**Bugs rencontrés**
- Sankey shape cassée avec données réelles → 2 causes : (1) pool déséquilibré sans `__disponible__` → fix invisible node ; (2) algo crossing ECharts réordonne → fix `layoutIterations: 0`
- `__disponible__` link encore visible après invisible node → le gradient mapper JS écrasait `opacity:0` → fix : `if (link.target === "__disponible__") return link`
- `animationDuration` ignoré → seulement au root level → fix : aussi dans series
- `subcat_totals` → `subcat_list` rename incomplet → boucle Sankey encore `for sub in subcat_totals` → fix
- Browser cache statique → hard refresh `Cmd+Shift+R` requis plusieurs fois (ECharts + JS statique)
- ImportLog file_hash bloquait re-import Yuh → fix : `ImportLog.objects.filter(file_name__icontains='yuh').delete()` en shell

**Reste à faire Phase 2B**
- KPIs comme onglets sélecteurs (Montant / Transactions / Objectif) — issue #22

---

## 2026-04-22 — Phase 2B : JS charts refactoring + page catégorie drill-down (VSCode)

**Contexte**
Suite de la session du matin : refactoring JS charts en fichiers statiques réutilisables, puis implémentation complète de la page catégorie drill-down (URL + vue + template + navigation depuis Sankey, Donut, liste). L'utilisateur a aussi exprimé les prochaines grandes features à planifier.

**Livré**
- ECharts 5.6.0 installé en local (`static/js/vendor/echarts.min.js`) — plus de CDN
- Refactoring JS → `static/js/charts/` :
  - `utils.js` : `window.BricCharts`, alias `BC.T` + `BC.FONT` + `BC.applyFactor()`
  - `sankey.js` : `BricCharts.initSankey(el, data, opts)` — gère pool/no-pool, marges auto
  - `donut.js` : `BricCharts.initDonut(el, data, opts)` — avec `onSegmentClick`
- `slug` ajouté sur nœuds Sankey + segments Donut (navigation au clic)
- `index.html` : liste catégories `div` → `<a href="{% url 'budget:category_detail' %}">` sur chaque ligne
- Navigation Sankey `onNodeClick` + Donut `onSegmentClick` → `window.location.href`
- URL `/budget/categorie/<slug>/` + vue `budget_category_detail()` + template `category_detail.html`
  - Header breadcrumb + 3 KPIs (total, count, moyenne calculée en Python)
  - Sankey direct Category → SubCategories (no pool, marges 10%)
  - Liste transactions avec right panel overlay wired (`hx-on::htmx:after-swap`)
- 3 issues GitHub créées et ajoutées au project board : #22 (cat detail), #23 (filtres), #24 (objectifs)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| CDN → local | ECharts depuis `static/js/vendor/` | Pas de dépendance externe runtime, RGPD, contrôle version |
| JS namespacing | `window.BricCharts` (IIFE pattern) | Pas de bundler (YAGNI) — debugging simple, ordre de chargement explicite |
| `hasPool` auto-detect | `nodes.some(n => n.name === "__pool__")` | 1 fonction `initSankey` pour les 3 variantes Sankey du projet |
| `openPanel()` sur detail cat | `hx-on::htmx:after-swap` sur container tx | Rows n'ont pas `openPanel()` — sur index.html c'est "Tout voir" qui ouvre ; sur la page catégorie chaque clic tx l'ouvre |
| `avg_amount` | Calculé en Python dans la vue (pas en template) | `divisibleby` Django = booléen, pas division — bug silencieux si calculé en template |

**Bugs rencontrés**
- `divisibleby` Django = test booléen → moyenne cassée → fix : calcul Python dans la vue
- `Edit` tool fail sur fichiers avec chars UTF-8 spéciaux (`─`, `—`, ` `) → fix : script Python inline avec `open(path, 'rb')` + `.replace()`
- Pre-commit djlint reformate les templates → re-stage après hooks requis à chaque commit

**Nouvelles features planifiées (non codées — à ajouter au backlog)**
- Export/backup des règles de catégorisation (avant session manuelle ~4h de classification)
- Import CSV drag & drop avec animation UX : détection banque → lecture → diff → résultat animé
- Monitoring compte : date du dernier import CSV par compte (à stocker dans `ImportLog`)
- Déploiement sur `main` : décision à prendre (critères : catégorisation complète + règles exportées)

**Reste à faire Phase 2B**
- Visual QA page catégorie dans le browser (Sankey + layout)
- KPIs comme onglets sélecteurs (Montant / Transactions / Objectif)
- Filtres multi-select sur index.html (#23)

---

## 2026-04-22 — Phase 2A : Sankey + Donut ECharts + design tokens + seed réaliste (VSCode)

**Contexte**
Session UI intensive : implémentation du Sankey cashflow et du donut distribution avec ECharts (choix mûri vs Chart.js). Itérations visuelles pour coller au style Finary. Refactoring des design tokens pour éliminer les couleurs hardcodées en JS. Seed réaliste 24 mois pour avoir des données visuellement représentatives.

**Livré**
- **ECharts choisi** à la place de Chart.js — meilleur support natif Sankey + Gauge + cohérence inter-graphiques
- **Sankey cashflow** — 3 colonnes (income → pool doré → expense), gradient sombre(0.25)→lumineux(1.0) gauche→droite, `opacity: 0.75` visible par défaut (ECharts défaut 0.2 = invisible), `emphasis.lineStyle.opacity: 1` au hover
- **Positionnement labels Finary-style** : income nodes `position: "right"` (sur le flux), expense nodes `position: "left"` (sur les courbes) — calculé en JS depuis les liens, `left: 0, right: 0` dans la série (correction : ignoré au niveau racine)
- **Pool node** : `__pool__` (nœud bridge doré `#f2c086`), label masqué, 3e colonne invisible
- **Donut distribution** — ECharts pie avec radius intérieur, label centre via `graphic`, légende textuelle
- **`window.BRICBUDGET_TOKENS`** : exposé dans `base.html` depuis `tailwind.config.theme.extend.colors` — source unique de vérité, plus de hex hardcodé dans les scripts JS
- **`window.BRICBUDGET_FONT`** : idem pour la police Inter
- **Tooltip sans hex** : `backgroundColor: T["surface-hover"]`, `borderColor: T["edge"]`
- **`dev_seed_realistic`** : 24 mois de transactions Geneva-réalistes, EXPENSE_BLUEPRINT + INCOME_BLUEPRINT, ratio 1.30×, jitter ±15%, make dev-seed-realistic FLUSH=1 MONTHS=24
- **Analyse flow Finary** : screenshots 02/04/33 — flow UX confirmé pour Phase 2B (clic catégorie → page drill-down avec Sankey sous-catégories)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Chart.js → ECharts | ECharts pour tous les graphiques | Sankey natif + gauge + cohérence palette. Chart.js plugin sankey = tier non maintenu |
| Design tokens JS | `window.BRICBUDGET_TOKENS` dans base.html | Une seule source de vérité (tailwind.config). Évite désynchronisations silencieuses (ex: gold `#d4a942` vs `#f2c086` réel) |
| `{# #}` multiligne | Interdit — utiliser `{% comment %}{% endcomment %}` | Django 6 : `{# #}` multiligne = texte brut rendu en HTML (connu, cf. QUESTIONS) |
| left/right Sankey | Doivent être dans la série (pas à la racine) | ECharts ignore silencieusement ces props au niveau racine pour les Sankey |
| Phase 2B flow | Page dédiée `/budget/categorie/<slug>/` | Navigation classique Django, Sankey drill-down (catégorie → sous-catégories) — pas de modal |

**Bugs rencontrés**
- `{# ... #}` multiligne dans base.html → texte rendu en clair sur la page → fix : `{% comment %}{% endcomment %}`
- `left/right/top/bottom` au niveau racine de `setOption` pour Sankey → ignorés silencieusement → fix : déplacer dans la série
- Gradient `color: LinearGradient` passé depuis Python (via json_script) → ECharts ne reconnaît pas l'objet → fix : calculer `echarts.graphic.LinearGradient` entièrement en JS
- `json.dumps()` + `json_script` = double-encodage → JS reçoit une string, pas un objet → fix : passer dict Python brut, `json_script` sérialise une seule fois
- Gradient visible seulement au hover → `lineStyle.opacity` ECharts Sankey défaut = 0.2 → fix : `opacity: 0.75` par lien

**Reste à faire (Phase 2A)**
- Refactor JS : extraire `static/js/bricbudget-charts.js` avec `BricBudget.initSankey()` / `BricBudget.initDonut()`
- Filtres catégories + compte (dropdown multi-select)
- Deuxième passe icônes

---

## 2026-04-22 — Phase 2A : refactor budget app + make test + pre-commit pytest (VSCode)

**Contexte**
Session d'architecture : extraction de l'app `budget/` depuis `transactions/` pour corriger la confusion namespace UI ↔ data layer, puis setup du filet de sécurité tests automatiques.

**Livré**
- **Évaluation Graphify/Obsidian** : rejeté — prématuré pour la taille actuelle du projet, overhead sans ROI
- **App `budget/` extraite** : `src/budget/views.py`, `src/budget/urls.py`, `src/templates/budget/` (10 templates) — copie depuis `transactions/` avec 4 adaptations (nom vue, chemins templates, redirects, app_name)
- **`transactions/`** : vidé de ses vues/urls — data layer pur (models, services, connectors)
- **`src/config/urls.py`** : `include("transactions.urls")` → `include("budget.urls")`
- **`sidebar.html`** : active state via `app_name == 'budget'` au lieu de `'transactions'`
- **Fix template include paths** : `{% include "transactions/_panel_*.html" %}` → `{% include "budget/_panel_*.html" %}` (3 fichiers — pattern distinct des namespaces URL)
- **`make test`** : nouvelle cible Makefile → `poetry run pytest --tb=short -q`
- **pre-commit hook pytest** : `language: system`, `pass_filenames: false`, `always_run: true` — bloque tout commit si un test échoue

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Graphify | Rejeté | Overhead de setup > gain token pour ce volume de code |
| Dépendance apps | `budget/` → `transactions/` (unidir.) | Django inter-app import normal, pas de circularité |
| Namespaces URL vs chemins templates | Deux `sed` séparés | `transactions:` (URL) et `"transactions/` (include path) sont deux patterns distincts |

**Bugs rencontrés**
- Ruff a bloqué le premier commit (auto-fix 3 erreurs + reformat 4 fichiers) → re-stage + commit : passé au 2ème essai
- `make test` : 31 erreurs PostgreSQL collation mismatch (macOS libcollate 2.36 → 2.41 après mise à jour OS) → fix : `ALTER DATABASE REFRESH COLLATION VERSION` sur `template1` + `bricbudget` → 88/88 ✅

**Reste à faire (Phase 2A)**
- Sankey cashflow, KPIs row, Distribution donut, filtres période/compte/catégorie
- Deuxième passe icônes

---

## 2026-04-18 — Phase 2A : suite de tests complète (VSCode)

**Contexte**
Session dédiée aux tests critiques identifiés lors de l'audit. Objectif : couvrir les fonctions critiques (parseurs, ImportService, taux de change, résolution compte) avant que la Phase 2A UI se construise dessus. 88 tests écrits, 0 échec.

**Livré**
- `pyproject.toml` : config pytest corrigée (`[tool.pytest.ini_options]` dans le bon TOML block) + deps `pytest ^9.0` + `pytest-django ^4.12`
- `conftest.py` (racine) : minimal, config Django dans pyproject.toml
- `src/tests/conftest.py` : fixture `cic_file` partagée (openpyxl, 2 feuilles, 5 tx EUR) — niveau parent pour être visible des tests connectors ET integration
- `src/tests/connectors/conftest.py` : fixtures `yuh_csv_path`, `ubs_csv_path`
- `src/tests/connectors/fixtures/yuh_sample.csv` : 5 lignes (4 tx + 1 REWARD_RECEIVED skippée)
- `src/tests/connectors/fixtures/ubs_sample.csv` : metadata 9 lignes + 3 tx, IBAN fictif `CH00 0000...`
- `src/tests/connectors/test_yuh.py` : 19 tests YuhConnector
- `src/tests/connectors/test_ubs.py` : 14 tests UBSConnector
- `src/tests/connectors/test_cic.py` : 22 tests CICConnector
- `src/tests/services/conftest.py` : fixtures `user`, `chf_account`, `eur_account`, helpers `make_tx()` / `make_file_hash()`
- `src/tests/services/test_import_service.py` : 9 tests ImportService (dédup, amount_chf, _find_rule, dry_run)
- `src/tests/services/test_get_exchange_rate.py` : 10 tests get_exchange_rate (cache DB, API mocké, erreurs réseau)
- `src/tests/integration/test_import_integration.py` : 8 tests E2E (CSV → parse → run → DB)
- `src/tests/commands/test_account_resolution.py` : 7 tests _find_account (Yuh : 0/1/2+/inactif, UBS : IBAN absent/introuvable/trouvé)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Fixture CIC | openpyxl programmatique (pas de .xlsx binaire) | Diffs lisibles dans git, pas de risque de corruption, modifiable sans Excel |
| Scope conftest | `cic_file` dans `src/tests/conftest.py` (pas `connectors/`) | pytest charge conftest hiérarchiquement — les tests integration doivent y accéder |
| Données de test | Toutes les identifiants (IBAN, RIBs) sont fictifs et inventés | Aucune donnée bancaire réelle en clair dans le repo |
| Branche | Tests sur `feature/phase-2a-budget-kpis` (pas une branche séparée) | Taux de change + tests sont liés — même branche cohérente |

**Bugs rencontrés**
- `pyproject.toml` : pytest config hors du bloc TOML (dans un commentaire) → pytest ne la trouvait pas → fix : réécriture complète
- CSV yuh_sample.csv : 5 séparateurs après CHF au lieu de 4 → EMPLOYER SA dans colonne FEES (11) au lieu de SENDER (10) → fix : retirer un `;`
- Fixture `cic_file` pas visible depuis `src/tests/integration/` → conftest.py au mauvais niveau → fix : monter au niveau `src/tests/`

**Reste à faire (Phase 2A)**
- Phase 2A UI : KPIs row, Sankey, Distribution donut, filtres période/compte/catégorie
- Deuxième passe icônes (affinage visuel avec données réelles)

---

## 2026-04-17 — Session 3 : outillage qualité + premier audit de déviation (VSCode)

**Contexte**
Session de meta-travail : renforcement des règles Git (branches obligatoires), création du système d'audit de déviation code ↔ documentation, et exécution du premier audit complet.

**Livré**
- `.claude/commands/update.md` : étape 0 bloquante branche + section GitHub milestones/project board + rappel audit
- `.claude/commands/audit.md` : entièrement réécrit — compare modèles↔Mermaid, templates↔specs UI, vues↔TASKS, connecteurs↔BaseConnector, conventions↔MEMO. Sauvegarde rapport dans `.claude/audits/`
- `.claude/commands/next.md` : règle Git ajoutée — vérifier branche avant tout code
- `.claude/HELLO.md` + `commands/hello.md` : lecture du dernier audit au démarrage, ligne `🔍 Dernier audit` dans le résumé
- `.claude/MEMO.md` : section Git réécrite avec règle `⛔ JAMAIS sur main`
- `.claude/audits/2026-04-17.md` : premier rapport — 8 dérives détectées, 4 actions prioritaires
- Mémoire persistante `feedback_git_branches.md`
- Logos banques SVG : `_resolve_bank_icon_map()` priorité `svg/` + fallback `miniature/`, rendu conditionnel `brightness-0 invert`
- Token filter : `description_raw.split("|")[0]` + length `>= 1`

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Audit historique | `.claude/audits/YYYY-MM-DD.md` | Traçabilité des dérives — `/hello` lit le dernier au démarrage |
| Branche obligatoire | Règle dans MEMO + 3 commandes + mémoire | Erreur session : commits directs sur `main` |
| Phase 2E | Marquée ✅ livrée en avance en 1C | Wizard complet livré 2026-04-17 |

**Bugs rencontrés**
- Logos banques noirs sur fond noir → `currentColor` + fond sombre → fix : `brightness-0 invert`
- Fausse alarme audit `target_field` → déjà `"description_raw"` dans `defaults` views.py:1067 ✅

**Reste à faire (avant Phase 2A)**
- Branche `feature/phase-2a-budget-kpis`
- Corriger `schema_db_v2.mermaid` (5 champs désynchronisés)
- Frankfurt API → `amount_chf` pour comptes EUR

---

## 2026-04-17 — Phase 1C : wizard règle intelligente + polish logos banques (VSCode)

**Contexte**
Session de code (suite). Objectif : finir le wizard de création de règle intelligente (chips keyword + picker + preview + confirmation), puis corriger l'affichage des logos banques (carré blanc moche sur dark theme).

**Livré**
- `transactions/views.py` : `budget_panel_rule_create()` — GET, tokens depuis `description_raw` (split sur `|` pour exclure métadonnées banque), custom_cats + system_cats
- `transactions/views.py` : `budget_rule_preview()` — POST, count transactions impactées SANS modifier
- `transactions/views.py` : `budget_rule_create_submit()` — POST, crée `CategorizationRule` + bulk apply (exclut `categorization_source=MANUAL`)
- `transactions/views.py` : `_resolve_bank_icon_map()` — logique hybride svg/ (priorité) + miniature/ (fallback PNG)
- `transactions/urls.py` : 3 nouvelles routes `panel/rule-create/`, `rule-preview/`, `rule-create/`
- `base_app.html` : toast CTA activé — bouton "Créer une règle" fonctionnel avec `hx-get` dynamique + `htmx.process(btn)`
- `_panel_rule_create.html` (nouveau) : bandeau transaction source + chips tokens cliquables + picker accordéon + hidden `#rule-keyword` + preview
- `_rule_cat_picker_row.html` (nouveau) : même rendu que `_cat_picker_row.html` mais POST vers `rule_preview`
- `_panel_rule_preview.html` (nouveau) : résumé règle + `affected_count` en grand + bouton Valider/Retour
- `_panel_rule_confirm.html` (nouveau) : confirmation post-création + updated_count
- `_cat_picker_row.html` : badge "perso" sur sous-catégories `is_system=False`
- `static/icons/banks/svg/` (nouveau dossier) : SVG `currentColor` sans fond pour yuh, ubs, finpension
- `components/banks/account_badge.html` : rendu conditionnel SVG (fond sombre + `brightness-0 invert`) vs PNG (fond blanc)

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Tokens depuis description_raw | `description_raw.split("\|")[0]` — partie avant `\|` seulement | Yuh met métadonnées (ID transaction, "PAIEMENT CARTE DE DEBIT") après `\|` — pas utile pour les règles |
| Filtre token length | `>= 1` (était `>= 2`) | "SAINT-CLAUDE" → "SAINT" + "C" — le "C" était silencieusement ignoré |
| Logos banques | SVG `currentColor` dans `svg/` — fallback PNG `miniature/` | PNG ont fond blanc intégré → carré blanc sur dark theme |
| Rendu SVG logos | `brightness-0 invert` (même pattern que icônes catégories) | `currentColor` dépend de la couleur CSS du parent — plus robuste de forcer blanc |

**Bugs rencontrés**
- Logos yuh/ubs noirs sur fond noir après migration vers SVG → `currentColor` héritait d'une couleur sombre → fix : `brightness-0 invert` force blanc
- CIC logo disparu après migration → CIC n'a pas de SVG dans `svg/` → fix : fallback `miniature/` PNG automatique

**Reste à faire (Phase 1C)**
- Taux de change (frankfurter.app → `ExchangeRate` → `amount_chf` pour CIC EUR, Carys GBP)
- Déclarer virement interne (reporté — `on_delete ignore()` suffit pour l'instant)

---

## 2026-04-17 — Phase 1C : panneau "Détails de la transaction" complet (VSCode)

**Contexte**
Session de code. Objectif : construire le panneau état C du right panel (détails d'une transaction), avec les deux toggles HTMX `is_ignored` et `is_reconciled`, et rewirer le flux de navigation.

**Livré**
- `transactions/views.py` : `budget_panel_tx_detail()` — vue GET, retourne `_panel_tx_detail.html`
- `transactions/views.py` : `budget_toggle_reconcile()` — POST, bascule `is_reconciled`, détecte `source` (list → row, detail → panneau)
- `transactions/views.py` : `budget_toggle_ignore()` étendu — détecte `source=detail` pour retourner `_panel_tx_detail.html` au lieu de `_panel_tx_row.html`
- `transactions/urls.py` : routes `panel/tx-detail/` + `transactions/<id>/toggle-reconcile/`
- `transactions/_panel_tx_detail.html` (nouveau) : nom + montant gros · catégorie cliquable → picker · Compte/Montant/Date · badge "RÈGLE INTELLIGENTE APPLIQUÉE" (si `categorization_source=rule|ai`) · 2 toggles HTMX fonctionnels
- `transactions/_panel_tx_row.html` : rewire clic → `panel_tx_detail` · badge vert `is_reconciled` (cercle `bg-income` + checkmark) · bouton pointer direct depuis la liste
- `transactions/admin.py` : `CategorizationRuleForm` avec `clean()` + `formfield_for_foreignkey` — filtre subcategory par category, empêche sélection incohérente

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Toggle source detection | Champ POST `source=detail` dans les forms | Une seule vue, deux comportements de retour selon contexte d'appel |
| Badge "Règle intelligente" | `categorization_source == "rule" or "ai"` → badge doré `text-gold` | Fidèle au pattern Finary, pas de PLUS badge (pas de tiers premium) |
| Pointer depuis la liste | Bouton direct sur la row (même pattern que oeil ignore) | UX : pas obligé d'ouvrir le détail pour juste pointer |
| Icône banque arrondie | `rounded-full` dans le panneau détail | Cohérence avec les icônes banque ailleurs dans l'app |

**Bugs rencontrés**
- `budget_toggle_ignore()` corps tronqué lors de la modification manuelle → vue retournait 500 · fix : corps complet réécrit
- `translate-x-4` insuffisant pour toggle ON → cercle sortait du pill · fix : `left-0.5` + `translate-x-4` = 18px total, marges symétriques 2px

**Reste à faire (Phase 1C)**
- Badge "perso" sur sous-catégories `is_system=False` dans le picker
- Note inline · Merchant name inline · Déclarer virement interne
- Bulk recatégorisation

---

## 2026-04-15 — Phase 1C : fix couleurs picker + planning panneau détail transaction (VSCode + Cowork)

**Contexte**
Session courte de polish UI + planning. Correction de la hiérarchie visuelle des icônes dans le picker catégorie, puis analyse du screenshot Finary "Détails de la transaction" et planification du panneau état C.

**Livré**
- `_cat_picker_row.html` : row "Principale" — restauration du cercle couleur plein (`colour_hex`) + icône blanche (`brightness-0 invert`). Hiérarchie finale : cercle plein = niveau catégorie (header + Principale), cercle 40% opacity = niveau sous-catégorie.
- `static/icons/categories/credit-card.svg` — nouvelle icône Tabler ajoutée.

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Panneau "Détails de la transaction" | À construire en Phase 1C (pas 2B) | Prérequis pour "Pointer" et "Inclure analyse" — vu screenshot Finary |
| "Pointer la transaction" | Toggle dans le panneau détail (pas checkbox dans la liste) | Cohérent avec Finary — la liste n'a pas de checkbox permanente pour ça |
| Flux clic transaction | tx row → panneau détail → clic catégorie → picker | Meilleure UX : voir les infos avant de catégoriser |
| Hiérarchie icônes picker | cercle plein = catégorie, cercle 40% = sous-cat | Annule tentative "inversion foncé/clair" qui ne marchait pas en dark theme |

**Reste à faire (Phase 1C)**
- Panneau "Détails de la transaction" (_panel_tx_detail.html) — 4 étapes planifiées
- Rewire clic tx row → détail (pas picker directement)
- Toggles is_ignored + is_reconciled dans le panneau détail

---

## 2026-04-07 — Phase 1B : Right Panel transactions + composants UI réutilisables (VSCode)

**Contexte**
Session UI focalisée sur le right panel "Tout voir" : liste transactions style Finary, navigation période dans le panel, recherche live HTMX, composants réutilisables.

**Livré**
- `transactions/_panel_tx_list.html` : fragment HTMX — liste transactions 5 colonnes (icône catégorie · description · badge compte · montant · checkbox), groupement par date `{% ifchanged %}`, sans séparateurs horizontaux
- `budget_panel_transactions()` : vue HTMX, lecture session, résolution icônes banque (priorité svg > png > jpg > jpeg), filtre `q` live search (`Q(merchant_name) | Q(description_raw)`), contexte enrichi (`period_mode`, `period_label`, `can_go_next`)
- `budget_panel_navigate(request, action)` : met à jour session puis délègue à `budget_panel_transactions` — même fragment, sans redirect
- URLs : `panel/transactions/` + `panel/transactions/<action>/`
- `components/period/period_nav.html` : composant navigation période réutilisable, deux modes (`href` page principale / `hx-get` panel HTMX) via `nav_url_name` + `htmx_target` — `budget.html` migré dessus
- `components/search/search_bar.html` : barre de recherche live HTMX — `hx-select="#tx-results"` préserve la search bar au swap, bouton × clear (`input:not(:placeholder-shown) ~ .search-clear-btn`), icône dorée au focus via `onfocus`/`onblur` inline
- `components/banks/account_badge.html` : composant badge banque réutilisable (icône + nom compte), intégré dans `_panel_tx_list.html`
- `Bank.domain` CharField + migration `0006_add_bank_domain.py`
- `update_bank_logos` management command : télécharge logos depuis Google Favicons API → `static/icons/banks/miniature/` + `make update-bank-logos`
- Right panel : flottant (`top-3 right-3`, marges 4 côtés), `bg-surface-2/70 backdrop-blur-xl` (camembert visible flou derrière), `rounded-2xl`

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `hx-select="#tx-results"` | HTMX extrait un sous-élément de la réponse serveur | Évite de remplacer la search bar au filtrage — valeur input préservée |
| Period nav component | `nav_url_name` variable + `{% url nav_url_name 'prev' %}` | Django url tag accepte une variable template — composant 100% réutilisable sans pre-calcul Python |
| Focus icône search | `onfocus` inline `style.color` au lieu de `group-focus-within` Tailwind | Tailwind CDN ne génère pas fiablement `group-focus-within` pour le contenu HTMX-injecté |
| CSS search bar | Styles dans `base.html`, pas dans le fragment HTMX | `<style>` dans innerHTML HTMX pas traité de façon fiable par tous les navigateurs |
| Google Favicons | Stockage local au `make update-bank-logos` | Pas de fetch à chaque refresh (1 requête par transaction × 200 tx = spam) |
| Fond blanc icônes banque | Tous sur fond blanc `bg-white p-1` | Contraste garanti (UBS = logo noir, fond noir = invisible) |

**Bugs rencontrés**
- `translate-x-full` insuffisant avec `right-3` → panel non masqué complètement → fix : `translate-x-[calc(100%+0.75rem)]` + JS adapté
- `group-focus-within:text-gold` pas généré par Tailwind CDN sur contenu HTMX → 3 tentatives CSS → fix final : `onfocus="this.previousElementSibling.style.color='#f2c086'"`
- Clearbit logos mort (acquisition HubSpot) → switché sur Google Favicons API

**Reste à faire**
- Catégorisation inline (Phase 1C)
- `uppercase` merchant_name à l'import (Phase 1C)
- Icônes catégories SVG (quand données réelles)

---

## 2026-04-07 — Phase 1B : Budget connecté DB + polish UI (VSCode + Claude Code)

**Contexte**
Suite directe de la session prototype. Objectif : brancher la page Budget sur la vraie DB, rendre la navigation fonctionnelle, et polir l'UI.

**Livré**
- `transaction_list()` connectée à PostgreSQL : Sum aggregation par catégorie, KPIs (Entrées / Sorties / Disponible / Récurrentes), donut math calculé en Python (dasharray/dashoffset)
- `budget_set_period()` : navigation prev/next + sélecteurs 1M/3M/1A via session Django, clamping sur le mois courant
- `budget_set_tab()` : onglets Entrées / Sorties fonctionnels, Récurrentes désactivé
- `transactions/urls.py` : 3 routes (list, period, tab)
- `transactions/templatetags/budget_filters.py` : filtres `|chf` (0 déc.) et `|chf_dec` (2 déc.) — séparateur milliers U+202F, virgule décimale — typographie FR
- Disponible : vert `text-income` si ≥ 0, rouge `text-expense` si négatif
- `components/badges/soon.html` : composant glassmorphism réutilisable — texte doré, fond bleu navy #1e1e6e semi-transparent, gradient border gold → bleu (60%), backdrop-blur, box-shadow glow
- `dev_randomize_categories` management command : assignment aléatoire avec coverage guarantee (aucune catégorie à 0). `make dev-randomize [ALL=1]`

**Décisions**
| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Donut math | Calculé en Python (vue), pas en template | Template logic = illisible. Python = testable |
| TAB_CONFIG dict | Mapping `active_tab → (liste, label_suffix)` dans la vue | Évite if/elif dans le template — clean |
| `dev_randomize_categories` | Phase 1 random + Phase 2 coverage guarantee | Sans coverage, certaines catégories = 0 → donut vide |
| Composants YAGNI | État vide inline dans budget.html, pas de composant | Un seul usage → abstraction prématurée inutile |
| Badge SOON | Composant `components/badges/soon.html` avec `{% include %}` + `with extra_class` | Deux usages (Récurrentes + Personnalisé) → composant justifié |

**Bugs rencontrés**
- `'budget_filters' is not a registered tag library` → `"transactions"` manquait dans `INSTALLED_APPS` (déjà présent, c'était un cache — redémarrage du serveur requis)
- `RecursionError: maximum recursion depth exceeded` → commentaire `{# #}` multiligne dans `soon.html` contenait `{% include 'components/badges/soon.html' %}` — Django 6 exécute les tags dans les commentaires multilignes → fix : `{% comment %}{% endcomment %}`
- `{# #}` sur plusieurs lignes en Django 6 = **pas un vrai commentaire** — le contenu est rendu et les tags sont exécutés. Règle : toujours `{% comment %}` pour les multilignes.

**Reste à faire (Phase 1B non critique)**
- Icônes catégories (`Category.icon` → SVG) — quand données réelles disponibles
- `components/ui/spinner.html` — utile seulement en Phase 1C (HTMX)

---

## 2026-04-07 — Phase 1B : Infrastructure UI + page Budget prototype (VSCode)

**Contexte**
Session de code. Objectif initial = vue Transactions. Pivot décidé en cours de session : on construit directement la page Budget (vue principale comme Finary) en hardcodé pour valider le design system avant de brancher la DB.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Topbar | Fixe, globale, pas de `{% block %}` override | Même contenu sur toutes les pages — évite la dispersion |
| Layout 2 panels | `panel_left` (flex-[2]) + `panel_right` (flex-[1]) dans `base_app.html` | Structure répétable sur toutes les pages Budget/Catégorie |
| Panels sans border | `bg-surface-3 rounded-xl` sans `border-edge` | Finary : les cartes se distinguent par la couleur, pas la bordure |
| Panels fit-content | Plus de `h-full` sur les cartes | Hauteur dictée par le contenu, fond visible sous le donut |
| `{% endblock %}` | Sans nom — `{% endblock topbar_title %}` interdit en Django 6 | Breaking change Django 6 (erreur `'block' tag takes only one argument`) |
| `{# #}` multilignes | Interdit — utiliser `{% comment %}{% endcomment %}` | Le lexer Django parse les `{% block %}` même dans les commentaires `{# #}` |
| `font-size: 13px` | Sur `<html>` — scale tous les `rem` Tailwind | Interface compacte sans modifier une seule classe |
| URL `/budget/` | Pointe sur `transaction_list` → `transactions/budget.html` | Renommage : `list.html` était un legacy trompeur |
| SVG icons hardcodés | OK pour prototype — remplacé quand DB branchée | `Category.icon` (CharField) + `static/icons/categories/<name>.svg` prévu |
| KPI tabs | Entrées/Sorties/Disponible/Dépenses récurrentes = tabs cliquables | Filtre la liste catégories selon le type de flux — comme Finary |

**Livré**

- `transactions/urls.py` + include dans `config/urls.py`
- `transactions/views.py` : `transaction_list()` minimale (hardcodée)
- `transactions/budget.html` : page Budget complète en prototype :
  - Nav période : pill ← date ▾ →, boutons circulaires 1M/3M/1A, pill Personnalisé
  - Header Cashflow + contrôles (toggle sous-cats, dropdowns rounded-full, copy/expand)
  - Placeholder Sankey
  - KPI tabs avec icônes, gold actif + underline, Disponible gris non-cliquable
  - Liste 6 catégories hardcodées (SVG icons dans cercles colorés, chevron hover gold)
  - Panel droit Distribution : SVG donut + légende pourcentages
  - Séparateurs `border-edge` entre sections
- `base_app.html` refactorisé : 2 blocs `panel_left`/`panel_right`, topbar globale, tout transparent
- `base.html` : `font-size: 13px`, tous `{% endblock name %}` → `{% endblock %}`
- `synthese/index.html` : mêmes corrections + blocs topbar morts supprimés
- `sidebar.html` : lien Budget câblé (`{% url 'transactions:list' %}`), active via `app_name`

**Corrigé (bugs découverts en session)**

- Django 6 : `{% endblock name %}` → `{% endblock %}` dans tous les templates
- `{# #}` multilignes avec `{% block %}` dedans → commentaires visibles en prod
- `bg-green-950/20` / `bg-blue-950/30` sur containers → masquait le `bb-background`

---

## 2026-04-06 — Phase 1B : Consolidation docs + décisions archi UI (Cowork)

**Contexte**
Session de nettoyage et consolidation. Pas de code écrit — mise à niveau des docs, GitHub, mémoire Claude.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Vue principale | **Budget** — pas Transactions | Finary : tout part du Budget. Transactions = drill-down ou page secondaire. |
| Page Transactions | Secondaire — review post-import, bulk catégorisation | Utile mais pas le cœur du produit |
| Right panel | Drill-down transactions d'une catégorie (HTMX depuis Budget) | Pattern Finary : clic catégorie → panneau latéral |
| Template tags custom (`budget_tags.py`, `amount.html`) | **Supprimés du plan** — YAGNI | `{% if amount > 0 %}` inline suffit. Pas besoin d'abstraction pour ça. |
| UI spec | `documentation/ui_budget_specs.md` | Emmanuel envoie ses screenshots Finary → notes structurées ici |
| GitHub CLI auth | `unset GITHUB_TOKEN` avant `gh` | `GITHUB_TOKEN` env var invalide prend priorité sur le keyring valide |
| Import COMMIT | `make import-yuh FILE=... COMMIT=1` | `COMMIT=1` = flag Make → `--commit` sur la management command |

**Livré**
- `HELLO.md` — réécriture complète : carte repo, documentation map, rappels opérationnels, format sortie
- `MEMO.md` — design tokens mis à jour (vrais tokens Tailwind, plus les hex bruts), section import corrigée, connecteurs marqués ✅
- `commands/hello.md` — skill `/hello` mis en cohérence avec HELLO.md
- GitHub Project Board : issue #16 Design System → Done, issue #12 body mis à jour, issue #15 URL params → sessions, issue #20 créée (Asset/Holding architecture)
- `TASKS.md` — Phase 1B infra ✅, Phase 2C ✅, Phase 4 enrichie avec architecture Asset/Holding complète

---

## 2026-04-06 — Phase 1B : Architecture UI templates (Cowork)

**Contexte**
Session architecture : définition de la structure templates, composants réutilisables, et design system pour toute l'UI. Inspiré de Finary. Basé sur recherche best practices Django 6 + HTMX + Tailwind.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Héritage templates | 2 niveaux max : `base.html` → `base_app.html` → page | Au-delà les `{% block %}` deviennent intraçables |
| Composants statiques | `{% include "components/..." with var=val %}` | Léger, natif Django, pas de dépendance |
| Composants avec logique | `@register.inclusion_tag` dans `templatetags/budget_tags.py` | Montants colorés et badges catégorie ont besoin de Python |
| Pas de django-components | Rejeté | 4x plus lent, overkill pour notre cas |
| Layout 3 colonnes | sidebar fixe + main scroll + right panel `fixed` slide-in | `fixed` = le panel sort du flux, ne pousse pas le contenu |
| Right panel | HTMX charge le contenu au clic, CSS transform l'ouvre/ferme | 2 fonctions JS (`openPanel` / `closePanel`) — rien de plus |
| Partials HTMX | Dossier `partials/` séparé, convention `_nom.html` | Distingue visuellement fragments vs pages complètes |
| État filtres | Session Django, `hx-push-url="false"` | Décision 2026-04-01 : pas d'URL params |
| Palette | Dark theme `#111318`, zinc-900 cards, emerald/red pour montants | Cohérence Finary, lisible sur fond sombre |
| Tailwind Phase 1B | CDN play (pas de build step) | ROI : build Tailwind plus tard quand les classes sont stabilisées |

**Livré**
- `documentation/ui_architecture.md` — spec complète : layout, héritage, composants, patterns HTMX, design tokens, ordre construction
- `TASKS.md` Phase 1B — tâches détaillées dans l'ordre de dépendance
- Branche `feature/phase-1b-transactions-ui` créée depuis `development`

**Sécurité (même session — Phase 1A bis)**
- RIBs CIC sortis du code → `.env` via `config()`
- Pre-commit hook `no-hardcoded-bank-ids` ajouté (IBAN CH/FR + séquences 20-22 chiffres)
- `reset_seed` corrigé : supprime `Transaction` + `ImportLog` avant `Account` (PROTECTED FK)
- `development` re-synchronisé avec `main` (2 commits sécurité manquants)

---

## 2026-04-06 — Phase 1A bis : ImportService + refacto architecture import (Cowork)

**Contexte**
Session architecture : refonte du pipeline d'import pour le rendre cohérent, maintenable, et réutilisable depuis l'UI.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Couche service | `transactions/services.py` : `ImportService` + `ImportResult` + `compute_file_hash` | Séparation responsabilités : commandes = thin wrapper, service = toute la logique DB |
| Commandes d'import | Refactorisées — appellent `ImportService.run()`, n'ont plus de logique DB | DRY : la même logique servira depuis l'UI (Phase 6) sans dupliquer |
| `--commit` flag | Sans flag = dry-run, avec `--commit` = écriture DB | Comportement dry-run conservé, progression explicite |
| `extract_account_identifier()` | Méthode standard sur `BaseConnector`, défaut `None` | Contrat uniforme — chaque connecteur expose l'identifiant qu'il peut extraire |
| `Account.contract_number` | Clé universelle de matching import → compte DB | Un seul champ, un seul lookup. Évite la dispersion sur `iban` / `account_reference` / convention |
| UBS IBAN | `extract_account_identifier()` retourne IBAN normalisé (sans espaces) | `contract_number` = IBAN normalisé en DB. `CheckingAccount.iban` gardé pour SEPA/affichage — rôles distincts |
| Yuh | `extract_account_identifier()` retourne `None` → fallback convention | Yuh n'expose pas d'identifiant dans le fichier — convention "1 seul compte Yuh actif" reste valide |
| CIC | Pas de `extract_account_identifier()` au niveau fichier — résolution par feuille | CIC = 1 fichier N comptes. Chaque feuille expose son RIB via `get_account_sheets()`. Exception structurelle, pas une incohérence |
| `BANK_SLUG` sur connector | **Supprimé** — lookup `contract_number` sans filtre bank | Évite le couplage connector↔DB slug. `contract_number` est globalement unique (IBAN, RIB, N° contrat le sont dans la réalité) |
| `amount_chf` | CHF → direct, EUR/GBP → `None` jusqu'à Phase 1C | frankfurter.app intégration reportée à Phase 1C |
| file_hash CIC | Suffixé par nom de feuille : `"sha1:Cpt 18027..."` | `ImportLog.file_hash` unique=True — un fichier CIC produit N ImportLog (1/compte) |

**Livré**
- `transactions/services.py` : `ImportService`, `ImportResult`, `compute_file_hash`
- `import_yuh.py`, `import_ubs.py`, `import_cic.py` : refactorisés, thin wrappers
- `.claude/MEMO.md` : section "Pipeline d'import" + "Matching account" ajoutées
- `.claude/TASKS.md` : Phase 1A fermée, tâches refacto connecteurs listées

**Reste (Phase 1A bis)**
- `connectors/base.py` : `extract_account_identifier()` à ajouter
- `connectors/ubs/parser.py` : `extract_iban()` → `extract_account_identifier()`
- Seed UBS : `contract_number` = IBAN normalisé
- `import_ubs.py` : utiliser le nouveau pattern

---

## 2026-04-03 — Phase 1A : Connecteurs Yuh + UBS, import dry-run (VSCode)

**Contexte**
Session code Phase 1A : parseurs CSV opérationnels, rapport d'import complet avec détection compte + carte.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Filtrage Yuh | **Blacklist** (`SKIPPED_ACTIVITY_TYPES`) au lieu de whitelist | Tout nouveau type d'activité Yuh importé par défaut — plus robuste |
| Seul exclu Yuh | `REWARD_RECEIVED` | Cashback points sans valeur CHF — pollue la liste |
| Détection compte Yuh | Convention `bank=yuh + type=checking` | Aucun identifiant dans le fichier Yuh — convention > détection |
| Détection compte UBS | IBAN extrait ligne 2 | UBS expose `IBAN:;CH94...;` en ligne 2 — matching DB normalisé (sans espaces) |
| Détection carte | `card_last_four` → `{last_four: Card}` dict, 1 query | O(1) par transaction, pas de query par ligne |
| `AccountType.CURRENT` | Renommé `CHECKING` + migration de données | Cohérence avec le modèle `CheckingAccount` — même vocabulaire partout |
| `Transaction.time` | Ajouté `TimeField(null=True)` | UBS exporte l'heure (`HH:MM:SS`), Yuh/CIC non — conserver l'info quand disponible |
| Seed cartes Yuh | `last_four` réels : Emmanuel=1150, Carys=8803 | Extraits du vrai fichier CSV — matching fonctionnel en rapport |
| Lookup key Card | `(user, checking_account)` → last_four en defaults | Permet de mettre à jour le last_four via re-seed sans créer de doublon |
| Phase 1B | Écriture DB non encore implémentée | Dry-run d'abord — valider les données avant de les pousser |

**Livré**
- `connectors/base.py` : `BaseConnector` + `TransactionDict` (contrat commun)
- `connectors/yuh/parser.py` : `YuhConnector` complet (blacklist, balance, carte, hash)
- `connectors/ubs/parser.py` : `UBSConnector` complet (IBAN, balance, time, hash)
- `transactions/management/commands/import_yuh.py` : rapport dry-run avec matching carte
- `transactions/management/commands/import_ubs.py` : rapport dry-run avec matching compte
- `accounts/migrations/0004_alter_account_account_type.py` : CURRENT→CHECKING + données
- `transactions/migrations/0002_transaction_time.py` : champ time ajouté
- `documentation/import_system.md` : schéma complet du pipeline d'import
- Seed mis à jour : Carys ajoutée sur Yuh, vrais last_four

**Résultats validés en test**
- Yuh : 226 tx parsées, 168 REWARD_RECEIVED skippées, `[emmanuel.barriol *1150]` + `[Carys *8803]` détectés
- UBS : 24 tx parsées, IBAN `CH9X XXXX XXXX XXXX XXXX X` extrait, balance 7281.45 CHF

**Reste Phase 1A**
- `connectors/cic/parser.py` (Excel multi-feuilles)
- `make import-cic`

---

> Journal de bord du projet. Une entrée par session de travail.
> Format : date · contexte · décisions · raisons · prochaine étape.
>
> Ce fichier est distinct de CLAUDE_MEMO.md (référence technique) et CLAUDE.md (briefing Claude).
> Il répond à la question : **"Qu'est-ce qui s'est passé et pourquoi ?"**

---

## 2026-04-02 — Phase 0B : seed_initial + reset_seed + icônes banques (VSCode)

**Contexte**
Session code : finalisation Phase 0B. Seed complet, commande reset, icônes banques organisées.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `update_or_create` vs `get_or_create` | **`update_or_create`** partout dans le seed | Le seed est la source de vérité — il doit propager les changements à la DB |
| Localisation commandes seed | **`config/management/commands/`** | Cross-app (touche accounts + transactions + users) — Two Scoops convention |
| Transactions dans le seed | **Non** | Les transactions viennent des vrais CSV (Phase 1A), pas de données fictives |
| Ajout de comptes | **Admin Django jusqu'au MVP**, UI dédiée en Phase 3+ | Comptes changent rarement, Carys n'est pas encore active |
| IBANs dans le seed | **Fictifs** (`CH00 0000 0000 0000 0000 Y`) | Placeholder — l'import CSV ne se base pas sur l'IBAN pour matcher |
| Boursorama icon | **Manquante** — à télécharger sur Brandfetch | Pas bloquant pour Phase 1A |

**Livré**
- `config/management/commands/seed_initial.py` : 4 banks, 7 accounts, 4 cards, 17 catégories + subcats
- `config/management/commands/reset_seed.py` : suppression ordonnée, confirmation interactive
- `Makefile` : `make seed` + `make reset-seed`
- `static/icons/banks/miniature/` : yuh.png, ubs.svg, cic.svg (+ others/ pour logos complets)

**Phase 0B fermée ✅**

---

## 2026-04-02 — Phase 0B : SavingsAccount + architecture types de comptes (VSCode)

**Contexte**
Session courte : analyse Finary pour comprendre la taxonomie des comptes, décision architecture, ajout `SavingsAccount`.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Taxonomie comptes | **2 familles** : Transactionnels (Checking + Savings) vs Positionnels (Investment, Crypto, Pension) | Transactionnels → Budget. Positionnels → Patrimoine Net. Logiques métier distinctes. |
| `SavingsAccount` | Créé maintenant (Phase 0B) | Bloquait le seed — CIC Livret A et LDDS en ont besoin |
| Identifiant compte | `account_reference` (texte libre) sur SavingsAccount, **pas d'IBAN** | L'IBAN est spécifique aux comptes courants SEPA. Livrets/Finpension/Invest = numéro de contrat propriétaire |
| `investments/` app | Phase 5 — `Instrument` + `Position` + `PriceHistory` | Les "supports" ne sont pas des comptes — séparation propre |
| Connecteurs | Identifient les comptes par **nom + banque**, pas par IBAN | Plus robuste, cohérent avec la suppression du slug |

**Livré**
- `accounts/models.py` : `SavingsAccount(OneToOne Account)` — interest_rate, account_reference
- `accounts/admin.py` : `SavingsAccountAdmin` enregistré
- `accounts/migrations/0003_savingsaccount.py` : migration appliquée

---

## 2026-04-01 — Phase 0B : Auth + Admin + Décisions architecture (VSCode + Cowork)

**Contexte**
Session code + architecture. Phase 0B partiellement livrée (seed_initial reste à faire).

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `Account.slug` | **Supprimé** (migration 0002) | Slug dérivé du name → incohérent si renommage. Connecteurs utilisent IBAN à la place |
| UI state | **Session Django uniquement** — pas d'URL params | Finary n'a pas d'URL params, HTMX + session reproduit ce comportement sans JS |
| UBS | **Ajouté** comme 3ème banque | Compte joint Emmanuel + Carys (CHF), 2 cartes |
| Carys | Apparaît dès Phase 0B (carte UBS) | Pas Phase 7 — elle a déjà une carte sur le compte commun UBS |
| `neutral` (categories.json) | Mappé `""` (blank) dans le seed | Neutral = pas de nature budget = exactement ce que blank représente |
| Parseur UBS | Analysé — CSV `;`, 8 lignes header, IBAN extractable ligne 2, IGNORER "Solde décompte" | Phase 1A |

**Livré**
- `settings.py` : LOGIN_URL, LOGIN_REDIRECT_URL, LOGOUT_REDIRECT_URL + commentaires complets
- `config/urls.py` : django.contrib.auth.urls ajouté
- `templates/registration/login.html` : template dark custom
- `accounts/admin.py` : Bank, Account, CheckingAccount, Card, BalanceSnapshot, ExchangeRate
- `transactions/admin.py` : Category, SubCategory, CategorizationRule, Transaction, ImportLog, BudgetTarget
- `accounts/migrations/0002_remove_account_slug.py` : Account.slug supprimé
- `transactions/management/commands/` : répertoire créé

**Cours donnés**
- Django templates : héritage, DIRS vs APP_DIRS, context processors
- HTMX : fragment partiel, état côté serveur, hx-post/hx-target/hx-swap
- Tailwind : classes utilitaires, django-tailwind, STATIC_URL vs STATICFILES_DIRS
- Chart.js : intégration via bloc `<script>` + JSON injecté depuis la view

**Reste Phase 0B**
- `seed_initial` management command + `seed.json` (Banks Yuh/UBS/CIC, Accounts, Cards)

---

## 2026-03-30 — Deep dive Finary + Challenge architecture (Cowork)

**Contexte**
Session stratégie : analyse des screenshots Finary et challenge du plan produit.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `Transaction.note` | **Ajouté** | Texte libre sur chaque transaction (ex: "loyer janvier") — vu dans Finary screenshot 18 |
| `Transaction.merchant_name` | **Renommé** (était `description_nette`) | Plus explicite, éditable par l'user, séparé du `description_brute` d'audit |
| `Transaction.is_ignored` | **Ajouté** | Exclure une transaction de tous les calculs et graphiques |
| `Transaction.is_internal_transfer` | **Ajouté** | Virement entre 2 comptes perso |
| `Transaction.paired_transaction` | **Ajouté** | FK self — lie les 2 côtés d'un virement interne. is_internal_transfer seul ne suffit pas |
| `Category.is_system` | **Ajouté** | Catégories système non supprimables (Inconnu, Virements) |
| `Account.solde_initial` | **Ajouté** | Solde d'ouverture — sans ça, les courbes de solde commencent à 0 |
| `Bank.icon_slug` | **Ajouté** | Identifiant icône banque pour l'UI |
| "Ignorer" = exclure de tout | **Décidé** | is_ignored → exclu cashflow + catégories + budget. Inclus dans le solde réel |
| Catégorie supprimée | **Décidé** | `on_delete=SET_DEFAULT` vers "Inconnu" |
| GitHub milestones | **Restructurés** | Sub-phases (0A, 0B, 1A...) au lieu de phases larges — plus clair |
| Phase 2C ajoutée | **Nouveau** | Design system + dark theme Tailwind dédié (palette BricBudget, glassmorphism) |

**Screenshots Finary analysés**
- 25 screenshots renommés avec contenu descriptif dans `assets/private/references/`
- Features UI identifiées : panneau latéral transaction, modal créer catégorie, Sankey sous-cats, donut fixe

**Fichiers mis à jour**
- `documentation/schema_db_v2.mermaid` — nouveaux champs + relation paired_transaction
- `.claude/MEMO.md` — sections Bank, Account, Transaction, Catégorisation enrichies
- `.claude/TASKS.md` — réécriture complète avec sub-phases 0A→3B
- GitHub : milestones sub-phases créés, issues reassignées et créées

---

## 2026-03-30 — Session code Phase 0A : users/ + accounts/ (VSCode)

**Contexte**
Première session de code sur les modèles Django. Architecture challengée et affinée en direct.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| `AccountAccess` | **Supprimé** | YAGNI — app 2 users, tout partagé. Emmanuel + Carys = "on fait un". Qui utilise quoi = `Card.user`, pas une table de permissions. |
| `AccountSpecification` | **Supprimé** | Remplacé par tables spécialisées par type : `CompteCourant` (Phase 0A), `CompteEpargne`, `ComptePrevoyance` (Phase 4+). Plus propre, pas de colonnes NULL. |
| Identifiant User | **Email** (pas username) | `CustomUser(AbstractUser)` + `CustomUserManager` + `USERNAME_FIELD = "email"` |
| `AUTH_USER_MODEL` | `"users.CustomUser"` défini avant toute migration | Sinon reset DB obligatoire |
| Login admin | Email + mot de passe fort généré | Commande `manage.py create_user --superuser` lisant depuis `.env` |
| `USE_I18N` | `False` | Admin Django forcé en anglais (indépendant de la langue du navigateur) |
| Backups | `make backup` / `make restore` via `pg_dump` | Protection données après reset DB accidentel |
| Yuh multi-devises | Un seul `Account` (devise = CHF) | Les devises EUR/USD sont au niveau des transactions, pas du compte |
| `on_delete` | `PROTECT` sur Bank→Account, `CASCADE` sur Account→enfants | PROTECT = pas de suppression accidentelle d'une banque avec des comptes |

**Modèles écrits et migrés**
- `users/` : `CustomUser`, `CustomUserManager`, `Profile` ✅
- `accounts/` en cours : `Bank`, `Account`, `CompteCourant`, `BalanceSnapshot` ✅
- `accounts/` à finir : `Card`, `ExchangeRate`
- `transactions/` : non commencé

**Fichiers créés / modifiés**
- `src/users/models.py`, `admin.py`, `management/commands/create_user.py`
- `src/accounts/models.py` (en cours)
- `src/config/settings.py` — AUTH_USER_MODEL, USE_I18N
- `Makefile` — create-superuser, backup, restore, admin URL
- `documentation/schema_db_v2.mermaid` — schéma complet mis à jour

---

## 2026-03-30 — Architecture apps Django (VSCode + Cowork)

**Contexte**
Challenge de l'architecture prévue : une seule app `core/` avec 15 modèles. Trop monolithique.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Apps Django | **2 apps : `accounts/` + `transactions/`** (au lieu de `core/`) | 15 modèles dans un seul `models.py` = illisible rapidement. Séparation par domaine métier. |
| `accounts/` | Bank, Account, AccountAccess, Card, AccountSpecification, BalanceSnapshot, ExchangeRate | Infrastructure bancaire — stable après setup initial |
| `transactions/` | Transaction, Category, SubCategory, CategorizationRule, ImportLog, BudgetTarget, BudgetResult | Flux financier quotidien — cœur vivant de l'app |
| `connectors/` | **Package Python pur** (pas une app Django) | Les parseurs n'ont pas de modèles ni de vues — pas besoin de l'ORM Django |
| Dépendance | `transactions` → `accounts` uniquement | FK unidirectionnel — pas de dépendance circulaire possible |
| Phase 5+ | App `investments/` ajoutée si besoin | Logique suffisamment distincte (positions, P&L, dividendes) pour mériter sa propre app |

**Règle de refactoring future**
Si `transactions/` grossit trop (Phase 3+), extraire `budget/` comme 3ème app. Chirurgical, sans impact sur `accounts/`.

**Ajout suite : app `users/`**
- `CustomUser (AbstractUser)` avec `USERNAME_FIELD = 'email'` → login par email
- `AUTH_USER_MODEL = 'users.CustomUser'` dans settings.py avant toute migration — sinon impossible à changer après
- `AccountAccess` reste dans `accounts/` (pas dans `users/`) — sinon dépendance circulaire : `users/` importerait `Account` depuis `accounts/` qui importe déjà `CustomUser` depuis `users/`
- Future : `django-allauth` pour Google OAuth / Passkeys — compatible AbstractUser sans refactoring
- Toujours référencer `settings.AUTH_USER_MODEL` dans les FK vers User, jamais `django.contrib.auth.models.User` directement

**Fichiers mis à jour**
- `.claude/TASKS.md` — Phase 0A : users/ + correction UserAccess → AccountAccess dans accounts/
- `.claude/MEMO.md` — structure projet + chaîne de dépendance
- `documentation/PROJECT_CHARTER.md` — tableau apps avec colonne "Dépend de"

---

## 2026-03-29 — Scaffold complet : Poetry + Django 6 + Docker + Makefile (VSCode)

**Contexte**
Première vraie session de code. Stack opérationnelle de zéro.

**Décisions**

| Sujet | Décision | Pourquoi |
|-------|----------|----------|
| Python | **3.13** (Homebrew) | Version la plus récente — stop aux vieilles versions |
| Package manager | **Poetry 2.x** avec `package-mode = false` | Gestion dépendances uniquement, pas de packaging |
| Django project name | **`config/`** (pas `bricbudget/`) | Two Scoops convention — le dossier `config/` n'est pas une app |
| PostgreSQL port | **5433** sur Mac → 5432 dans Docker | Évite conflit avec Homebrew PostgreSQL@16 sur le port 5432 |
| .env naming | `.env` (pas `.env.local` ni `.env.dev`) | python-decouple le lit automatiquement |
| Makefile | Avec couleurs ANSI (`printf`) + emojis + `make status` | `echo` macOS n'interprète pas les séquences ANSI |

**Problèmes rencontrés**
- Homebrew PostgreSQL@16 (launchd) occupait le port 5432 → Docker mappé sur 5433
- Poetry 2.x refuse de faire `env use` si sa propre version Python ne satisfait pas `requires-python` → venv créé via pyenv local 3.13.5
- `package-mode` doit être dans `[tool.poetry]`, pas dans `[project]`
- `echo` sur macOS ne rend pas les couleurs ANSI → remplacé par `printf` dans le Makefile

**Stack opérationnelle**
- `make run` → Django welcome page sur localhost:8000 ✅
- `make migrate` → migrations appliquées sur PostgreSQL 16 ✅
- `make status` → état des services avec ports ✅

**Fichiers créés / modifiés**
- `pyproject.toml` — Poetry, Python 3.13, Django 6, psycopg2, decouple, ruff, djlint, commitizen
- `poetry.lock`
- `docker-compose.yml` — PostgreSQL 16, port 5433, healthcheck
- `.env` + `.env.example`
- `src/config/settings.py` — PostgreSQL, Europe/Zurich, STATICFILES
- `src/config/urls.py`, `wsgi.py`, `asgi.py`
- `src/manage.py`
- `Makefile` — up/down/run/migrate/makemigrations/shell/logs/status
- `.python-version` — 3.13.5 (pyenv local)
- `documentation/PROJECT_CHARTER.md` — v2.1, Django 6, .env naming

**Prochaine étape**
Samedi 2026-04-05 : créer l'app `core/` + tous les modèles DB + `make migrate`

---

## 2026-03-28 — Architecture complète + structure projet (Cowork)

**Décisions**
- Feature set complet défini en 6 phases (Modules 0→6), voir `documentation/PROJECT_CHARTER.md`
- Schéma DB v2 architecturé : 13 tables, extensible par connecteur, voir `documentation/schema_db_v2.mermaid`
- Stack DevOps définie : ruff + djlint + pre-commit + GitHub Actions CI
- Structure `.claude/` créée — dossier dédié aux instructions agent (CLAUDE.md, MEMO.md, TASKS.md, HELLO.md)
- HELLO protocol défini : au démarrage Claude fait git log + CHANGELOG + TASKS → résumé 5 lignes
- `.gitignore` créé : assets/data/ et .env hors Git, tout le reste versionné
- `TASKS.md` mis à jour avec la nouvelle stack et les phases

**Fichiers créés**
- `.claude/CLAUDE.md` — briefing Claude (déplacé depuis racine)
- `.claude/MEMO.md` — référence technique complète
- `.claude/TASKS.md` — plan d'action phases 0→6
- `.claude/HELLO.md` — protocole de démarrage de session
- `documentation/PROJECT_CHARTER.md` — vision, features, estimations
- `documentation/schema_db_v2.mermaid` — schéma DB complet
- `.gitignore`

**À faire manuellement**
- Supprimer `CLAUDE.md` et `CLAUDE_MEMO.md` à la racine (doublons, remplacés par `.claude/`)

**Timeline**
- MVP utilisable (Phases 0+1+2) : ~10-11 semaines → mi-juin 2026
- App complète : ~23 samedis → automne 2026

---

## 2026-03-27 — Pivot de stack (Cowork)

**Contexte**
Session de planification architecture. Pas encore de code écrit dans `src/`.

**Décisions**

| Avant | Après | Pourquoi |
|-------|-------|----------|
| Plotly Dash | **Django** | Envie de se faire plaisir, meilleure scalabilité, admin gratuit, chemin SaaS clair |
| SQLite | **PostgreSQL** (Docker) | Plus robuste, prêt pour la croissance |
| Callbacks Dash | **HTMX** | Dynamisme sans JavaScript — état côté serveur, zéro JS à débugger |
| CSS custom | **Tailwind CSS** | Classes utilitaires, plus rapide, plus cohérent |

**Gestion de l'état UI**
- Problème posé : au refresh, les filtres/checkboxes/périodes de graphiques seraient perdus.
- Solution retenue : **Django sessions** pour l'état fonctionnel (filtres, checkboxes, dropdowns) + **URL params** pour les graphiques (bookmarkable).
- HTMX envoie une requête au serveur → Django lit/écrit la session → re-rend uniquement le fragment HTML concerné.

**Fichiers mis à jour**
- `code_agent/CLAUDE.md` — briefing Claude mis à jour (nouvelle stack)
- `code_agent/CLAUDE_MEMO.md` — section stack migrée + entrée historique ajoutée
- `CHANGELOG.md` — créé (ce fichier)

**Prochaine étape**
Scaffolding Django : structure `src/`, `requirements.txt`, `docker-compose.yml`, premier modèle `Transaction`.

---

## 2026-03-18 — Structure projet (Cowork, session 4)

**Décisions**
- Structure dossiers créée : `src/` `assets/` `n8n/` `data/raw/yuh|cic|finpension/`
- `TASKS.md` créé avec plan daté semaine par semaine (MVP V1 cible : 10 mai 2026)
- Workflow défini : Cowork (stratégie) / VSCode (code) / Claude.ai (prototypes)
- App locale Mac : données ne quittent pas le Mac
- Architecture proxy Claude API : tool use local, user_id injecté serveur, jamais dans le prompt

---

## 2026-03-17 — Business plan + CIC (Cowork, session 3)

**Décisions**
- CIC France ajouté : 3 comptes EUR, format Excel multi-feuilles analysé
- Dossier `business/` créé avec business plan complet (BricBudget)
- Business plan : marché CH (200k Yuh users, 2.2M expats), modèle freemium CHF 9/mois
- Concept "Parseur Vivant" : LLM schema detection → staging → validation → bibliothèque partagée

---

## 2026-03-17 — Framework budget (Cowork, session 2)

**Décisions**
- Clarification ANTEIS SA = salaire Merz Aesthetics (entité légale)
- Finpension déprioritisé → Phase 2
- Framework budget : Base Zéro + Pay Yourself First
- Taxonomie 5 natures de flux : `fixe_incompressible` / `fixe_compressible` / `variable_incompressible` / `variable_compressible` / `epargne`
- Structure app : 4 vues (Dashboard / Transactions / Budget / Tendances)

---

## 2026-03-17 — Session fondatrice (claude.ai)

**Décisions**
- Découverte emails Finpension + CSV Yuh (sept 2025 → mars 2026)
- Finary = France uniquement → notre app = tout le reste
- Choix stack Dash (à l'époque), rejet React/Streamlit/Reflex
- Prototype interactif fonctionnel avec vraies données Yuh
- 17 catégories + sous-catégories définies
- Schéma SQL défini
- Architecture pipeline complète
