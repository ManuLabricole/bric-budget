# UI Patrimoine Specs — BricBudget
> Notes prises sur screenshots Finary — Source de vérité pour coder la section Patrimoine.
> Mis à jour : 2026-04-28 (session analyse UX)
>
> Screenshots de référence : `assets/private/references/finary_layout/`
> Convention de nommage : `patrimoine-<vue>-<état>.png` (minuscules, tirets, sans accents)
>
> ⚠️  Pour lire un screenshot depuis Claude : cp vers /tmp/capN.png si le nom contient des
>      caractères spéciaux macOS (NFD), puis Read /tmp/capN.png.

---

## Index des screenshots — Patrimoine (28 avril 2026)

| Fichier | Contenu | Analysé |
|---------|---------|---------|
| `patrimoine-sidebar-comptes-bancaires-actif.png` | Sidebar : Patrimoine déplié, "Comptes bancaires" actif (gold) | ✅ |
| `patrimoine-sidebar-patrimoine-ferme-gold.png` | Sidebar : "Patrimoine" fermé, border gold, chevron → | ✅ |
| `patrimoine-comptes-vue-principale-liste-comptes.png` | Page Comptes bancaires : total 9 874 €, area chart, liste + donut | ✅ |
| `patrimoine-comptes-liste-groupee-par-banque.png` | Tab Comptes : liste groupée Yuh / CIC / Boursobank (sous-comptes masqués) | ✅ |
| `patrimoine-comptes-onglet-transactions-detail-panel.png` | Tab Transactions : liste + panel droit "Détails de la transaction" | ✅ |
| `patrimoine-compte-detail-cic-start-infos-panel.png` | Page compte CIC START : solde + area chart + panel Détails (IBAN/BIC) | ✅ |
| `patrimoine-compte-detail-menu-modifier-supprimer.png` | Page compte CIC START : menu 3-dot ouvert (Modifier / Supprimer) | ✅ |
| `patrimoine-transactions-filtres-barre.png` | Barre filtres : Tous les montants / Catégories / Toutes les transactions | ✅ |
| `patrimoine-transactions-filtre-montants-dropdown.png` | Dropdown montants : Tout / Revenus / Dépenses / Montant (avec opérateurs) | ✅ |
| `patrimoine-transactions-filtre-categories-dropdown.png` | Dropdown catégories : liste avec cercles colorés | ✅ |
| `patrimoine-transactions-filtre-etat-dropdown.png` | Dropdown état : Toutes / Pointées uniquement / Non pointées uniquement | ✅ |

---

## Navigation — Structure sidebar (confirmée)

```
Sidebar (160px fixe)
├── Synthèse                   → /synthese/  (SKIP Phase 4)
├── Patrimoine ▼               → collapsible
│   ├── Actions & Fonds        → SOON
│   ├── Livrets                → SOON
│   ├── Comptes bancaires ●   → /patrimoine/comptes/  ← Phase 3A
│   ├── Fonds euros            → SOON
│   └── Crypto                 → SOON
├── Analyse                    → SOON
├── Budget                     → /budget/   ← déjà livré
├── Importer                   → /import/   ← Phase 2F
└── Paramètres                 → SOON
```

**Comportement sidebar Patrimoine :**
- État fermé : label "Patrimoine" + chevron `→` + border gold si actif
- État ouvert : sous-items indentés (pas d'icône), item actif = fond `bg-surface-3` + texte gold
- Toggle : JS minimal (`classList.toggle('hidden')`) + session Django `sidebar_patrimoine_open`

---

## PAGE "Comptes bancaires" — `/patrimoine/comptes/`

### Layout global
```
SIDEBAR (160px) | MAIN panel_left (flex-2) | panel_right (flex-1)
```
Identique au layout Budget — réutilise `base_app.html`.

### panel_left

**Header :**
```
[←]  Comptes bancaires
```
- `[←]` = lien retour `/patrimoine/` (futur) ou breadcrumb
- Pas de breadcrumb complexe pour Phase 3A

**KPI principal :**
- Total consolidé tous comptes actifs : ex. `9 874 €`
- Devise = EUR (affichage en EUR, valeurs en `balance_chf` ou `balance` selon compte)
- Date snapshot : date du dernier `BalanceSnapshot`

**Period nav :**
```
[Empilé] [1J] [7J] [1M] [3M] [YTD] [1A] [TOUT]
```
8 options (vs 4 sur Budget). "Empilé" = mode area chart stacked par compte.
→ Stocké en session : `request.session['patrimoine_period']`
→ Phase 3A : implémenter 1M / 3M / 1A / TOUT uniquement (les autres SOON)

**Area chart :**
- ECharts `line` ou `area` (pas Sankey)
- X = dates, Y = solde total comptes (ou par compte si "Empilé")
- Source : `BalanceSnapshot` ordonnés par date
- ⚠️ Si pas de BalanceSnapshot en DB → afficher état vide "Aucune donnée de solde"

**Tabs :**
```
[Comptes●]  [Transactions]
```
- Stocké en session : `request.session['patrimoine_comptes_tab']`
- HTMX swap de la zone liste sous les tabs

### Tab "Comptes"

**Liste groupée par banque :**
```
─ Yuh ──────────────────────────────── 5 880 €  [›]
    Courant                             5 880 €  [›]
─ CIC ──────────────────────────────── 3 950 €  [›]
    CIC START          [ℹ️]             3 950 €  [›]
─ Boursobank ───────────────────────    42,83 €  [›]
    BOURSO BANK        [ℹ️]              42,83 €  [›]
```

- Header banque : `bank.name` + total consolidé banque + chevron
- Expand/collapse : HTML `<details>/<summary>` natif (pas HTMX)
- Sous-compte `[ℹ️]` : tooltip ou lien vers détail compte
- Montant banque = sum des `BalanceSnapshot.balance_chf` actifs de cette banque
- Montant compte = dernier `BalanceSnapshot.balance` (dans la devise du compte)
- Chevron `[›]` = lien vers `/patrimoine/comptes/<id>/`

**Django queryset :**
```python
from itertools import groupby
accounts = (
    Account.objects.filter(is_active=True)
    .select_related('bank', 'checkingaccount', 'savingsaccount')
    .order_by('bank__name', 'name')
)
# Pour chaque account : dernier snapshot
from accounts.models import BalanceSnapshot
for account in accounts:
    account.last_snapshot = (
        BalanceSnapshot.objects.filter(account=account)
        .order_by('-date')
        .first()
    )
# Grouper par banque
accounts_by_bank = {bank: list(accs) for bank, accs in groupby(accounts, key=lambda a: a.bank)}
```

### Tab "Transactions"

**Barre de recherche + filtres :**
```
[🔍 Chercher une transaction]   [Afficher les filtres]
[Tous les montants ▾]  [Catégories ▾]  [Toutes les transactions ▾]
```

Identique aux filtres du Budget right panel. Réutiliser la même logique session.

**Liste transactions :**
- Toutes les transactions de tous les comptes actifs (filtrées par période session)
- Groupées par date (même format `_panel_tx_row.html` du Budget)
- Clic transaction → panel_right = "Détails de la transaction"
- Réutiliser `_panel_tx_row.html` + `_panel_tx_detail.html` du Budget
  - Paramètre `source=patrimoine` pour différencier le contexte si besoin

**Sessions Django :**
```python
request.session['patrimoine_filter_amount']   = 'all' | 'income' | 'expense' | {'op': '<=', 'value': 500}
request.session['patrimoine_filter_category'] = [1, 3, 5]   # IDs Category, None = toutes
request.session['patrimoine_filter_state']    = 'all' | 'reconciled' | 'not_reconciled'
```

### panel_right "Distribution"

- Donut ECharts : répartition des soldes par compte (ou par banque)
- Identique au donut Budget — réutilise `window.BricCharts` namespace
- Segments : un par compte actif, couleur = `bank.colour` (à définir) ou couleur Tailwind auto
- Centre donut : "Total" + montant consolidé
- Synchronisé avec la liste (si filtre compte appliqué → donut mis à jour)

---

## PAGE "Détail compte" — `/patrimoine/comptes/<id>/`

### Header
```
[←]  [logo banque]  CIC START  [ℹ️]  [ ⋯ ]
```
- `[←]` = retour `/patrimoine/comptes/`
- `[logo banque]` = `static/icons/banks/<bank.icon_slug>.svg` (déjà en DB)
- `[ℹ️]` = info compte (lien interne ou tooltip)
- `[ ⋯ ]` = 3-dot menu : **Modifier** / **Supprimer**

### KPI + Chart
- Solde actuel : dernier `BalanceSnapshot.balance` + devise (`balance_chf` si conversion)
- Period nav (mêmes 8 options, période stockée en session)
- Area chart balance : historique `BalanceSnapshot` pour ce compte
- Si pas de snapshots → état vide avec message

### Tab "Transactions"
- Transactions filtrées sur `account=this_account` + période
- Même liste + filtres que le tab Transactions de la page liste
- Même partials HTMX

### panel_right "Détails du compte"
```
Banque          CIC
Devise          EUR
Type            Compte courant
Taux d'intérêt  0%
IBAN            FR76 **** 0108  [👁]
BIC             CMCIFRPPXXX     [👁]
```
- `[👁]` = toggle afficher/masquer IBAN complet (JS local, pas HTMX)
- IBAN masqué par défaut : `FR76 **** 0108` (4 premiers + 4 derniers)
- Source : `CheckingAccount.iban` (masqué) + `bic`
- Type : `Account.account_type` → libellé lisible ("Compte courant", "Livret A", etc.)
- **Sécurité** : IBAN masqué par défaut — l'IBAN réel en DB est lu via `config()` depuis `.env`

### Menu 3-dot (cap7)
```
[ Modifier ]    → modal HTMX pour renommer le compte ou changer le type
[ Supprimer ]   → confirmation HTMX + suppression logique (is_active = False)
```
- **Modifier** : `budget_modal_target_create()` pattern (GET modal + POST update)
- **Supprimer** : `is_active = False` — pas de delete physique, cacher de la liste

---

## FILTRES TRANSACTIONS — Spécification complète

Identiques aux filtres du Budget right panel (déjà spécifiés dans `ui_budget_specs.md`) :

### "Tous les montants" dropdown
```
Tout ✓
───────────
Revenus
Dépenses
───────────
Montant
  [Inférieur ou égal à ▾]  [  valeur  ]
```
- Section type : Tout (défaut) / Revenus / Dépenses
- Section range : opérateur + valeur numérique

### "Catégories" dropdown
- Multi-select avec cercles colorés (couleur `Category.colour_hex`)
- Toutes cochées par défaut

### "Toutes les transactions" dropdown
```
✓ Toutes les transactions
  Pointées uniquement
  Non pointées uniquement
```
Radio (sélection unique).

---

## RÉUTILISATION — Partials Budget existants

Ces partials sont **réutilisables sans modification** pour Patrimoine :

| Partial | Chemin | Usage dans Patrimoine |
|---------|--------|-----------------------|
| `_panel_tx_row.html` | `src/templates/budget/` | Ligne transaction dans liste |
| `_panel_tx_detail.html` | `src/templates/budget/` | Détail transaction (panel droit) |
| `_panel_category_picker.html` | `src/templates/budget/` | Changer catégorie d'une transaction |
| `period_nav.html` | `src/templates/components/period/` | Navigation période |
| `search_bar.html` | `src/templates/components/search/` | Barre recherche transactions |
| `account_badge.html` | `src/templates/components/banks/` | Badge banque sur une transaction |
| `soon.html` | `src/templates/components/badges/` | Badge SOON sur features futures |
| `budget_filters.py` | `src/transactions/templatetags/` | Tags `\|chf`, `\|chf_dec` |

---

## DÉCISIONS ARCHITECTURE — Phase 3A

| Sujet | Décision | Raison |
|-------|----------|--------|
| App Django | `src/patrimoine/` (nouvelle app) | Séparation responsabilités — modèles dans `accounts/`, vues dans `patrimoine/` |
| Sidebar | "Comptes (SOON)" → "Patrimoine ▼" collapsible | Aligne avec navigation Finary |
| Synthèse | SKIP Phase 4 | Données patrimoine complet inexistantes (pas de Finpension/ETFs) |
| IBAN affiché | Masqué par défaut `FR76 **** 0108` | Sécurité — pas de données sensibles en clair |
| BalanceSnapshot manquant | Afficher état vide, pas d'erreur | DB peut être vide pour les nouveaux comptes |
| Period nav | 4 options Phase 3A (1M/3M/1A/TOUT), 4 autres SOON | Simplicité — mêmes queries que Budget |

---

## PLANNING — Phase 3A

### Session 1 (~3h)
- App `src/patrimoine/` créée + câblée
- Sidebar refacto (Patrimoine collapsible)
- Vue `patrimoine_comptes_index()` + template `comptes/index.html`
- Tab Comptes : liste groupée par banque (expand HTML natif)
- Panel right : donut répartition

### Session 2 (~3h)
- Tab Transactions + filtres (session) + HTMX
- Vue `patrimoine_compte_detail()` + template `comptes/detail.html`
- Panel right "Détails compte" (IBAN masqué, BIC)
- 3-dot menu Modifier/Supprimer
- Area chart balance (ECharts, réutilise BricCharts)
