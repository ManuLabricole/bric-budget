## v1.0.0 (2026-06-26)

### BREAKING CHANGE

- première version stable 1.0.0 — fin de la phase 0.x pré-release.

### Feat

- **infra**: durcir le Dockerfile — user non-root + PYTHONDONTWRITEBYTECODE
- **infra**: Dockerfile (pg_dump 18) → contrôle du build, remplace Railpack/nixpacks

### Fix

- **infra**: gunicorn en PID 1 via exec (retour CodeRabbit #265)

## v0.2.0 (2026-06-26)

### Feat

- **infra**: Sentry (erreurs 500 + scrub PII) + healthcheck deploy Railway (#259, #187)
- **infra**: backup auto DB → S3 avant chaque deploy + cron-ready (#257)
- **budget**: objectifs en jauges dans la topbar (globales) + titre catégorie Finary + dropdown (#24)
- **seed**: commande seed perso (#146)
- **security**: couche-2 ORM fail-closed — OwnedManager par défaut (#213)
- **demo**: seed des categories perso pour le user demo (+ helper seed_perso_categories)
- **demo**: page admin /admin/demo/ pour seed/reset (acces facile, #118)
- **budget**: filtre money:currency — afficher la devise sur tous les montants
- **demo**: 3 banques × (courant+épargne) + CIC EUR + soldes + fixtures (#118)
- **demo**: règles de catégorisation démo + outillage fixtures (#118)
- **demo**: seeder via le pipeline d'import + commandes dev_seed/dev_reset (#118)
- **demo**: app demo + persona + générateurs de fichiers bancaires synthétiques
- **seed**: scope seed_categories sur owner=None + retrait des perso du référentiel
- **design**: colour_hex stable sur Account/Institution + branchement charts patrimoine
- **transactions**: unicité catégories scopée par owner (#137)
- **categories**: owner FK sur Category + SubCategory (multi-user safe)
- **design**: règle d'allocation couleur + exposition BRICBUDGET_TOKENS.palette (#134)
- **design**: palette dérivée primary/light/dark générée et committée (#134)
- **patrimoine**: page zoom compte + édition inline IBAN/BIC/taux (#82 PR C)
- **logos**: réparation manuelle d'un logo par URL — bucket Railway + picker (#128)
- **référentiels**: seeds distinguent créé / modifié / inchangé (fin du « mis à jour » trompeur)
- **admin**: action « resynchroniser les référentiels » sur Institution et Category
- **transactions**: sync_reference_data — parapluie référentiels du release deploy
- **transactions**: référentiel catégories committé + seed durci (échec bruyant, dry-run, is_active)
- **accounts**: identité d'import obligatoire — IBAN ou n° de contrat
- **patrimoine**: wizard création de compte — picker vers formulaire HTMX
- **accounts**: service create_account — dispatch type vers Details, atomique
- **patrimoine**: classe d'actifs Prévoyance (SOON) pour pension_3a/lp
- **accounts**: logos des nouvelles institutions (catalogue 135)
- **accounts**: champ category sur Institution (bank/investment/crypto)
- **patrimoine**: picker « Compléter mon patrimoine » + recherche live
- **accounts**: logos institutions (Google Favicons, cache static)
- **accounts**: catalogue 135 institutions FR/CH/UK + champ category
- **accounts**: catalogue 55 institutions FR/CH + domain dans seed_banks
- **services**: logs structurés clé=valeur dans fetch_logo
- **services**: fallback www. dans fetch_logo
- **services**: micro-service logos + backfill_logos + auto-fetch post_save
- **budget,patrimoine**: carte détail transaction inline réutilisable
- **auth**: landing page + login redesign + redirects prod-ready (#115)
- **patrimoine**: onglets Comptes/Transactions + liste institutions avec valeurs + treemap (#82)
- **patrimoine**: page classe d'actifs — graphe + période + stacked + distribution (#82)
- **patrimoine**: filtre & période en HTMX (swap sans reload) + seed enrichi (#82)
- **patrimoine**: filtre par classe d'actifs — composant réutilisable (#82)
- **patrimoine**: logos comptes, dégradé courbe, seed démo dev, titres (#82)
- **patrimoine**: page bilan overview — courbe net worth + table actifs + donut (#82)
- **patrimoine**: services bilan (BilanNode) + chart_data (#82)
- **patrimoine**: fondations services bilan — color, fix balance_chf, valuation (#82)
- **patrimoine**: Patrimoine = lien bilan + chevron toggle + page bilan placeholder (#82)
- **patrimoine**: PR A — coquille navigable par classe d'actifs + moteur de solde (#82)
- **accounts**: Phase 3A — Account extensions + Institution rename + models refactor (#116)

### Fix

- **infra**: retours CodeRabbit #260 — secret hors historique, restore gz, dump atomique, IBAN espaces
- **security**: Sentry — couper la fuite des variables locales + scrub par valeur (audit #260)
- **infra**: durcir backup DB — décodage creds URL, secret hors argv, rotation best-effort (#257)
- **budget**: tooltip objectif réellement visible + E2E hit-test pixel (#24)
- **security**: backfill des lignes fuitées + typage factory (retours CodeRabbit/CI #203)
- **security**: CASCADE owner sur Category/SubCategory à la suppression d'un user
- **deps**: resynchroniser poetry.lock avec pyproject.toml
- **tests**: mypy vert sur les tests d'intégration cross-module
- **ci**: release.yml — gate main + distinguer no-bump des vraies erreurs
- **ci**: durcir deploy-guard — permissions, persist-credentials, migrate, curl timeouts
- **ci**: durcir supply-chain — permissions read-only + persist-credentials
- **ci**: SBOM npm — --package-lock-only (cyclonedx-npm sans node_modules)
- **ci**: SBOM cyclonedx-py — flag correct --output-file (pas --outfile)
- **demo**: seed idempotent sur une DB pré-#202 (collision IBAN)
- **e2e**: importer expect (playwright.sync_api) — suggestion CodeRabbit commitee sans son import
- **e2e**: wait_for_url au lieu d'expect_navigation deprecie dans login() (#159)
- **seed**: cible canonique display_name + test delta règles système (#146)
- **tests**: annoter owner=None de SystemCategoryFactory pour mypy (#194)
- **security**: F1 — scoper les FK posées dans budget_rule_edit_submit (IDOR write)
- **migration**: rendre 0022 réellement réversible en multi-user (revue #206)
- **security**: BudgetTarget.owner — un objectif par user, fin du partage cross-user (#201)
- **demo**: scoper apply_rules au user démo dans seed_demo (revue #207)
- **security**: scoper les règles de catégorisation à l'utilisateur (#205)
- **security**: scoper les comptes démo par marqueur déterministe is_demo (#202)
- **demo,budget**: traiter les findings revue CodeRabbit (PR #200)
- **security**: scoper rules_count dans les vues gestion catégories (#118)
- **security**: colmater les fuites IDOR du référentiel budget (#118)
- **transactions**: contrainte sous-cat (category, name) scopee owner — multi-user perso (#137)
- **budget**: ouvrir le modal sur e.detail.target (htmx 2.x, listener delegue au body)
- **budget**: scoper les sous-categories par owner (fuite IDOR pickers + previews, SR-001)
- **imports**: convertir balance_chf des snapshots non-CHF (solde patrimoine en CHF)
- **imports**: le compte choisi au picker Yuh est perdu au confirm (#118)
- **tests**: isolation du cache d'icônes + pytest-randomly (#192)
- **rules**: scoper CategorizationRule par owner (IDOR SR-001)
- **types**: narrow obj en Category/SubCategory pour mypy (#137)
- **budget**: adapter lookups catégories au slug owner-scopé (#137)
- **deps**: bump cryptography 48.0.1 + msgpack 1.2.1 (CVE pip-audit)
- **logos**: aligner les variables storage sur le preset Railway « AWS SDK » (#128)
- **logos**: durcir la réparation par URL suite à la revue sécu (#128)
- **référentiels**: findings revue — seed_initial délègue les catégories, Makefile dev_reset_*
- **patrimoine**: erreurs wizard en 422, CTA doré plein, anti-bleu navigateur
- **patrimoine,accounts**: corrections revue PR #129
- **deps**: Django 6.0.5 → 6.0.6 — 5 CVEs (PYSEC-2026-197→201)
- **patrimoine**: EmptyPage → dernière page (stop scroll infini) + test (#82)
- **tests**: import_markers date — localtime() pour éviter décalage UTC vs local (#82)
- **patrimoine**: treemap couleurs, seed sans doublons institutions, tooltip confine, séparateurs transparents (#82)
- **patrimoine**: sha1 → sha256 dans dev_seed (semgrep SAST)
- **patrimoine**: border de dépliage sans flash + tokens surface harmonisés (#82)
- **patrimoine**: sidebar — Patrimoine en 2e position + indentation + highlight (#82)
- **deploy**: hotfix — healthcheck 301→200 + fixes Qodo/CI (#112)

### Refactor

- **budget**: guard HTMX + test isolation objectifs (retours reviewer #24)
- **seed**: type hints + doc idempotence get_or_create (#146)
- **imports**: extraire imports/orchestrator.py (prepare/run/persist)
- **import**: découper ImportService.run() + services.py en package
- **accounts**: Account.iban source unique — supprimer CheckingAccount.iban (#82)
- **logos**: source unique services.logos pour la résolution d'icônes (#139)
- **imports**: bank_slug → institution_slug — contrat POST + session (#140)
- **institutions**: purge legacy « bank » — tout passe sur Institution (#133)
- **seed**: seed_initial = référentiels seuls, comptes perso via setup_accounts
- **patrimoine**: résolution findings code review — N+1, déduplications, tests tab (#82)
- **patrimoine**: toggle sidebar en CSS pur — animation chevron + accordéon (#82)

### Perf

- **ci**: ne plus rejouer la CI au merge sur development (push: main only)

## v0.1.0 (2026-05-21)

### Feat

- **rules**: export JSON toutes les règles + bouton dans le panel (#48)
- **panel**: scroll infini + filtre montant min/max — issue #12 (#47)
- **deploy**: Phase 2H — Sécurité & Déploiement Railway (#45)
- **phase-2g**: rules CRUD + sécurité IDOR + audit loop
- **2G**: Rules CRUD + Sankey fix + tests coverage + IDOR imports
- **ui**: supprimer icône poubelle sous-catégories dans category_detail
- **budget**: badge 'mouvement interne' dans le panneau détail transaction
- **budget**: toggle décimales dans Paramètres (T6)
- **2G**: T4b/T4c — panel fixes + sync virement + Account.members M2M
- **2G**: T4 — apply_rules command + 6 tests intégration
- **2G**: T3 — créer/supprimer catégories + panel gestion + 186 tests
- **2G**: display_name champ stocké + cleanup UI legacy merchant_name
- **2G**: T2 — règle standalone depuis dropdown Créer
- **imports**: Phase 2F/2G — import storage, CASCADE, date_min/max, fix computed_balance
- **budget**: make lint/check + icônes sous-catégories dans rule_row
- **budget**: CRUD règles de catégorisation — panel modal + inline edit
- **development**: merge feature/phase-2f-import — UI fixes CHF + category picker
- **transactions**: commande reset_categories — positif → Revenus, négatif → Inconnu
- **budget**: filtres multi-select comptes+catégories, préférences décimales, export règles
- **ui**: bank_icon_url tag + bank_logo.html — logos cohérents partout
- **imports**: redesign page Activité — chart ECharts + boutons période/métrique
- **imports**: redesign historique — filename, totaux, badge matching IBAN/RIB/CONV
- **phase-2f**: import UI complet — accounts wizard + CIC multi-sheet + bug fixes
- **phase-2f**: redesign page import — sync KPIs + bar chart + upload compact panel droit
- **imports**: delete import + Transaction.import_log FK — suppression propre par import
- **phase-2f**: upload flow complet — dry-run HTMX + confirm + steps animés
- **phase-2f**: import history list + right panel detail (HTMX)
- **phase-2f**: scaffold app imports — /import/ accessible + sidebar item
- **connectors**: resolver + dual BalanceSnapshot + doc DB
- **category_detail**: panel fixe tx detail + badge fix + alignement
- import_all command + Sankey/donut fallback + dev subcategory assign
- **phase-2c**: tab Objectif complet — bar chart 12 mois + gauge SVG réutilisable
- **phase-2b**: KPI tabs + SVG progress arcs + sidebar polish + Sankey no-income
- **phase-2b**: BudgetTarget CRUD + wizard règle fixes + UX polish
- **phase-2b**: Sankey shape fixes + category detail polish + Soon badges
- **phase-2b**: category detail page + JS charts refactoring
- **phase-2a**: sankey cashflow + donut distribution + seed réaliste 24 mois
- **phase-2a**: exchange rate via frankfurter.app — amount_chf for non-CHF accounts
- **phase-1c**: wizard règle intelligente + polish logos banques SVG
- **phase-1c**: étape preview avant validation règle + bouton Valider/Retour
- **phase-1c**: rule picker — chips keyword cliquables + picker catégorie avec icônes
- **phase-1c**: wizard création règle intelligente + bulk apply
- **phase-1c**: badge perso sur sous-catégories is_system=False dans le picker
- **phase-1c**: transaction detail panel + pointer/ignore toggles
- **ui**: add subcategory icons in picker (light on dark bg)
- **ui**: category icons + picker redesign with principale row
- **icons**: first pass icon corrections + 9 new Tabler SVGs
- **ui**: display Tabler SVG icons in category picker and tx row
- **icons**: add 105 Tabler Icons SVGs for categories/subcategories
- **categories**: add is_system field to SubCategory model
- **phase-1c**: bouton créer catégorie — style gold rounded-full, aligné à droite
- **phase-1c**: polish UI picker catégorie — alignement Finary
- **phase-1c**: catégorisation inline HTMX + toast confirmation
- **phase-1c**: ignore transaction HTMX inline toggle
- **phase-1b**: right panel transactions + composants UI réutilisables
- **phase-1b**: budget connecté DB + nav période + onglets + composants
- **phase-1b**: affinage background + sidebar hover Finary
- **phase-1b**: layout 3 colonnes + design system Finary
- **security**: move CIC RIBs to .env + add pre-commit hook for bank IDs
- **security**: read UBS IBAN from .env via python-decouple in seed_initial
- **phase-1a**: ImportService + unified import pipeline + account matching via contract_number
- **phase-1a**: CIC connector + contract_number + multi-card support
- **phase-1a**: connecteurs Yuh + UBS, import dry-run avec matching compte + carte
- **phase-0b**: seed_initial + reset_seed + bank icons
- **accounts**: add SavingsAccount model (interest_rate, account_reference)
- **phase-0b**: auth login/logout, admin panels, remove Account.slug
- **connectors**: add connectors/ package skeleton
- **transactions**: add all Phase 0A transaction models
- **accounts**: add Bank, Account, CompteCourant, BalanceSnapshot models
- **users**: register CustomUser + Profile in Django admin
- **users**: CustomUser + Profile + UserManager

### Fix

- **deploy**: SECURE_PROXY_SSL_HEADER — Railway edge proxy SSL, évite boucle redirect
- **deploy**: SECRET_KEY inline pour collectstatic — Railway n'injecte pas les vars pendant build
- **security**: corrections Qodo PR#46 — 5 findings
- **security**: issue #42 — SEC-01/02/03 + OBS-01 + OPS-02
- **security**: correction 4 findings Qodo PR#43 — scope tx counts, migration, ValueError, env key
- **security**: 3 IDOR Qodo PR#43 + AccountQuerySet.for_user() + audit loop
- **template**: supprimer commentaire multiline {# #} non supporté par Django
- **budget**: Sankey + KPIs mis à jour sans reload après toggle is_ignored
- **budget**: HX-Redirect après toggle depuis panneau détail — Sankey + KPIs frais
- **budget**: sync OOB — mise à jour ligne après toggle depuis panneau détail
- **budget**: 'Classifiée' au lieu de 'Détectée' — badge mouvement interne
- **budget**: inverser toggle 'Exclure de l'analyse budgétaire'
- **ubs**: UBS prefix stripping + tests _clean_merchant + env RAILWAY_TOKEN
- **security**: SEC-01 — IDOR Transaction — filter by user on 7 views
- **2G**: services.py logging/race-condition + _clean_description minimal refacto
- **budget**: picker règle — layout identique à _cat_picker_row.html
- **budget**: picker règle — text-left sur les boutons (centrage browser default)
- **budget**: picker règle — design Finary (icônes alignées, fond light sous-cats)
- **budget**: suppression préférence décimales + lien admin catégories via {% url %}
- **ui**: CHF partout + category picker in-page + scroll-to-detail + tab fixes
- **ui**: sankey + donut category_detail — nœud 'Sans sous-catégorie' pour transactions non ventilées
- **ui**: toggle ignore depuis category_detail → HX-Redirect recharge KPIs + Sankey
- **ui**: category_detail — transactions ignorées visibles en grisé + séparateur date même fond
- **ui**: category_detail — séparateurs de date dans la liste transactions
- **ui**: logos banques toujours fond blanc — bank_logo.html simplifié + ubs.svg.bak + account_badge délègue
- **imports**: logos banques → bank_logo.html sur fond blanc (steps_create_account + import_detail)
- **phase-2a**: add User-Agent header for frankfurter.app (403 without it)
- **phase-1c**: bandeau transaction source — texte non tronqué, wrap autorisé
- **phase-1c**: tokens toujours depuis description_raw (cohérent avec Finary)
- **phase-1c**: tokens depuis merchant_name en priorité (moins de bruit)
- **seed**: delete Transactions + ImportLogs before Accounts in reset_seed
- **security**: remove real UBS IBAN from code — replace with placeholders
- **seed**: move commands to transactions/ app (visible in INSTALLED_APPS)

### Refactor

- **connectors**: homogenize parsers — SHA256 + shared _normalize_merchant
- extract budget app — views, urls, templates hors de transactions/
- translate all models and code to English
