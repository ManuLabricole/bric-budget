# Project Charter — BricBudget
> Version 2.1 — 2026-03-30
> Rythme : ~3h le samedi matin. Parfois +1h en semaine si motivation.
>
> Ce document = le "pourquoi" : vision, principes, stack, décisions d'architecture.
> Le "quoi/quand" = GitHub Issues + Milestones + Project Board.

---

## Vision

Remplacer Finary pour tout ce qui n'est pas France/EUR : un système de gestion de budget et de patrimoine personnel, multi-pays, multi-devises, auto-hébergé, avec une architecture extensible pour ajouter n'importe quel compte en créant un seul parseur.

**Finary = France / EUR. BricBudget = tout le reste (CH, UK, et au-delà).**

---

## Principes non négociables

- **Code simple et debuggable** — print() + stack trace. Pas de magie.
- **Extensible sans refactoring** — ajouter un compte = 1 parseur + 1 ligne en DB.
- **Données personnelles locales** — rien ne quitte le Mac Mini.
- **Auth dès le début** — Emmanuel + Carys, comptes séparés, vue commune possible.
- **Environnement contrôlé** — Docker Compose, pas de "ça marche sur ma machine".
- **Apprentissage** — Emmanuel veut comprendre chaque ligne. Code pédagogique, commenté sur le pourquoi.

---

## Stack technique — FINALE

| Couche | Outil | Raison |
|--------|-------|--------|
| Framework web | **Django 6.x** | ORM, admin, auth, migrations — tout inclus |
| UI dynamique | **HTMX 2.x** | Zéro JavaScript custom, état côté serveur |
| CSS | **Tailwind CSS 3.x** | Classes utilitaires, dark mode natif |
| Base de données | **PostgreSQL 16** | Robuste, JSON natif, fenêtres SQL |
| Graphiques | **Chart.js** via CDN | Simple, léger, compatible HTMX |
| Tâches async | **Django-Q2** | Cron jobs, watcher iCloud, import auto |
| Reverse proxy | **Nginx** (prod) | Accès Tailscale depuis l'extérieur |
| Containerisation | **Docker Compose** | Django + PostgreSQL + Django-Q + Nginx |
| Conversion devises | **frankfurter.app** | API gratuite, open source |

**Rejetés (avec raisons) :**
- ❌ Plotly Dash → moins scalable, pas d'admin, route SaaS fermée
- ❌ SQLite → remplacé par PostgreSQL pour robustesse et croissance
- ❌ React → boîte noire, Emmanuel ne peut pas débugger seul
- ❌ Streamlit → design rigide, re-run complet sur chaque interaction

---

## Architecture DB — Décisions clés

### Ownership des comptes
- `CompteAcces(compte_id, user_id, role: owner|viewer)` — many-to-many
- Max 2 users par compte (enforced au niveau applicatif)
- Emmanuel seul → 1 ligne owner. Emmanuel + Carys → 2 lignes (owner + viewer ou owner + owner)

### Cartes
- `CarteUtilisateur(compte_id, user_id, ...)` — 1 carte = 1 user + 1 compte
- Exemple : compte UBS → carte Emmanuel (*4521) + carte Carys (*8832)
- Champ `type: debit | credit` prévu dès le début, **carte de crédit développée en Phase future**

### Spécifications de compte
- `AccountSpecification` (one-to-one avec Compte) : champs spécifiques par type (taux Livret A, plafond LDDS, frais Finpension, type ETF acc/dist, limite crédit...)
- Champ `metadata jsonb` pour tout ce qu'on n'a pas anticipé
- Permet d'enrichir sans migration de `Compte`

### Calcul du solde
- `SoldeSnapshot` à chaque import (source de vérité pour les graphiques)
- Solde recalculé `SUM(Transaction.montant)` pour vérification de cohérence
- Les deux en parallèle

### Catégorisation
- Règles keywords d'abord (`RegleCategorisation`)
- Claude API en fallback pour les libellés inconnus
- Correction manuelle → génère automatiquement une nouvelle règle

### Architecture "connecteur"
- `BaseConnector.parse(filepath) → List[TransactionDict]`
- Chaque source = 1 fichier `parser.py` indépendant
- Service d'import commun : déduplication SHA1, insertion, snapshot solde, ImportLog

---

## DevOps

```
.env            → Dev local (DEBUG=True, DB locale) — jamais dans Git
.env.prod       → Production Mac Mini (DEBUG=False, secrets réels) — jamais dans Git
.env.example    → Template versionné dans Git (sans secrets)
```

### Qualité du code
```yaml
# pre-commit hooks
- ruff         # lint + format Python
- djlint       # lint templates Django/HTMX
- commitizen   # commits conventionnels (feat/fix/chore)
```

### Conventions de commit
```
feat(transactions): add inline category edit via HTMX
fix(parseur-yuh): handle BOM encoding in CSV
chore(deps): upgrade Django to 5.1.2
docs(charter): add investment module spec
```

### CI GitHub Actions (minimal)
```yaml
# Sur chaque push + PR
- ruff check .
- ruff format --check .
- python manage.py check --deploy
- pytest --tb=short
```

---

## Roadmap — Vue d'ensemble

| Phase | Contenu | Cible |
|-------|---------|-------|
| **0** | Fondations : scaffold, Docker, auth, modèles, admin, import Yuh | Avril 2026 |
| **1** | MVP Transactions : table, filtres, catégorisation, HTMX inline | Mai 2026 |
| **2** | Dashboard Cashflow : KPIs, charts, Sankey, dark theme | Mai-Juin 2026 |
| **3** | Budget & Objectifs : cibles, réalisé, alertes | Juin 2026 |
| **4+** | Patrimoine Net, CIC, Finpension, Investissements Yuh | Automne 2026 |
| **5+** | Automatisation, n8n, Tailscale, Claude API | Fin 2026 |

**MVP V1 (Phases 0-3) : mi-juin 2026**

Le détail des tâches par phase est dans GitHub Issues / Milestones.

---

## Ce qui n'est PAS dans le scope (pour l'instant)

- Multi-tenant SaaS (backlog lointain)
- App mobile
- Connexion directe bancaire (scraping) — illégal en Suisse sans agrément
- Notifications push / email
- Intelligence prédictive / projections
