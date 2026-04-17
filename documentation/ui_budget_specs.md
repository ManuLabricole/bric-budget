# UI Budget Specs — BricBudget
> Notes prises sur screenshots Finary. Source de vérité pour coder la page Budget.
> Mise à jour au fil des sessions — référencer avant de toucher Budget.
>
> Screenshots de référence : `assets/private/references/finary_screenshot/` (01-27)
> Screenshots budget-spec organisés en sous-dossiers :
>   `budget_spec/overview/`        — vue générale + KPIs
>   `budget_spec/filters/`         — filtres catégories + toggle sous-cats
>   `budget_spec/right_panel/`     — tout voir + filtres right panel
>   `budget_spec/category_page/`   — page catégorie + tabs + historique
>   `budget_spec/categorization/`  — flow catégorisation + wizard règle (cat_flow_01→11)
>
> Convention de prise de notes :
> - Couleurs → toujours en tokens BricBudget (`text-gold`, `bg-surface-3`) jamais en hex
> - Comportements HTMX → noter le trigger, la target, le partial
> - Données Django → noter les querysets nécessaires
> - États → noter default / hover / actif / vide / loading séparément

---

## Screens de référence existants (à analyser)

| Fichier | Contenu |
|---------|---------|
| `02_budget_cashflow_waterfall_11_categories_donut.png` | Vue Budget principale — waterfall + donut |
| `03_budget_cashflow_dropdown_categories_ouvert_sankey_arriere_plan.png` | Dropdown catégories ouvert + Sankey derrière |
| `04_budget_cashflow_sankey_sous_categories_2_filtres.png` | Sankey avec 2 filtres catégories actifs |
| `05_budget_dropdown_17_categories_icones_chevrons.png` | Liste complète 17 catégories avec icônes |
| `06_budget_cashflow_kpis_revenus_sorties_disponible_mars_2026.png` | KPIs row avec montants réels |
| `07_budget_cashflow_mars_2026_montants_floutes.png` | Même vue, montants floutés |
| `16_budget_cashflow_3mois_janv_mars_2026_13_categories_donut.png` | Vue 3 mois — filtre période |
| `17_budget_cashflow_janv_mars_2026_vue_reduite_categories_liste.png` | Vue réduite — liste catégories sans graphe |
| `18_budget_virements_liste_transactions_detail_panneau_modifier.png` | Right panel — liste transactions + modifier |
| `21_transaction_modifier_categorie_panneau_liste_17_categories.png` | Right panel — catégorisation |
| `22_transaction_modifier_sous_categories_alimentation_boissons.png` | Right panel — sous-catégories |
| `26_budget_transaction_details.png` | Right panel — détail transaction |

---

## Specs à compléter (noter ici au fil des sessions)

> Chaque section ci-dessous sera complétée quand Emmanuel envoie le screenshot correspondant.

---

---

## PAGE BUDGET — Vue générale
*Screenshot : `budget_spec/budget_overview_3m_entrées.png`*

### Layout global

```
SIDEBAR (160px)  |  MAIN CONTENT (flex-1)  |  DISTRIBUTION PANEL (fixed ~380px)
```

- Sidebar : navigation verticale, `Budget` en état actif (fond `bg-surface-hover/30`, texte `text-gold`)
- Main : scroll vertical, fond transparent (gradient visible)
- Distribution panel : **fixe à droite**, toujours visible, pas de slide-in — contient le donut

### Topbar (dans le main)

```
[← date range ▾]          [1M] [3M●] [1A] [Personnalisé]
```

- Sélecteur de période : format `1 févr. 2026 - 30 avr. 2026` avec chevron dropdown
- Boutons période : `1M` · `3M` · `1A` · `Personnalisé` — actif = fond `bg-surface-hover` + texte `text-text-base`
- Période active ici : **3M**

### Section Cashflow

**Titre + contrôles :**
```
"Cashflow"   [Sous-catégories ○]   [Toutes les catégories ▾]   [Tous les comptes ▾]   [📷] [⤢]
```
- Toggle `Sous-catégories` : OFF par défaut → Sankey source→cible. ON → drill-down sous-catégories
- Dropdown `Toutes les catégories` : filtre multi-select (toutes cochées par défaut)
- Dropdown `Tous les comptes` : filtre multi-select comptes
- Icône 📷 : screenshot du graph. Icône ⤢ : plein écran

**Graphique Sankey :**
- **Pas un waterfall** — c'est un Sankey (flux de gauche à droite)
- Gauche = sources (catégories entrées) : `Revenus 76%` · `Investissements 19.1%` · `Virements 4.9%`
- Droite = destinations (catégories dépenses) avec % et montant au hover
- Couleurs des flux : `text-income` (vert) pour revenus, nuances pour catégories
- Watermark Finary en bas à gauche
- Hauteur ~200px, fond très sombre `bg-surface-1`

### KPIs Row

Position : **sous le graphique** (pas au-dessus)

```
[↓ Entrées]     [↑ Sorties]     [○ Disponible]     [↻ Dépenses récurrentes ⓘ]
+30 743 €       -12 038 €       +18 705 €           -64 €
```

- Chaque KPI = icône + label + montant grand format
- Montant **cliquable** → filtre la liste catégories dessous
- Actif (`Entrées` ici) : montant en `text-gold`, label en `text-text-base`
- Inactif : montant `text-text-secondary`, label `text-text-muted`
- `Disponible` = `Entrées − Sorties` (hors virements internes + ignorés)
- `Dépenses récurrentes` : icône ⓘ au hover → tooltip explication
- Formule Django : `Transaction.objects.filter(period, account).aggregate(Sum('amount_chf'))`

**Boutons à droite des KPIs :**
- `Tout voir` → ouvre right panel ou page transactions complète
- `Créer ▾` → dropdown (créer règle, catégorie, budget target)
- `Paramètres ▾` → dropdown paramètres budget

### Liste catégories

- Titre dynamique : `"3 catégories d'entrées"` — change selon KPI actif + filtres
- **Filtre par KPI** : clic `Entrées` → affiche seulement catégories `income`. Clic `Sorties` → catégories dépenses
- Chaque ligne :
  ```
  [●icône couleur]  [Nom catégorie]          [+/- montant €]  [›]
  ```
  - Icône : cercle couleur `category.colour_hex`, emoji catégorie dedans
  - Montant : `text-income` si positif, `text-expense` si négatif
  - Chevron `›` → clic = charge liste transactions dans right panel (HTMX)
  - Hover ligne : `bg-surface-hover/30`
- Tri : par montant absolu décroissant

### Distribution Panel (droite fixe)

- Titre : `"Distribution"`, `text-text-base`
- Donut Chart.js centré
- Centre donut : label (`"Somme entrées"`) + montant total (`+30 743,32 €`) en `text-gold`
- Segments : couleurs des catégories affichées
- Synchronisé avec le filtre KPI actif (si `Entrées` → donut = répartition entrées)
- **Pas de slide-in** — fixe, toujours visible, contrairement au right panel transactions

---

## KPI actif — comportement au clic (Sorties)
*Screenshot : `budget_spec/budget_sorties_categories_budgets.png`*

### Ce qui change quand on clique "Sorties"

| Élément | Entrées actif | Sorties actif |
|---------|--------------|---------------|
| KPI actif | `Entrées` souligné + `text-gold` | `Sorties` souligné + `text-expense` |
| Titre liste | "3 catégories d'entrées" | "12 catégories de sorties" |
| Catégories listées | Revenus · Investissements · Virements | Toutes les catégories de dépenses |
| Donut centre | "Somme entrées +30 743 €" | "Somme sorties -12 037,87 €" |
| Donut couleurs | 3 segments verts/teals | Multicolore (1 couleur/catégorie) |
| Sankey | **Inchangé** — toujours le même | **Inchangé** |

→ Le Sankey ne réagit PAS au clic KPI. Il est toujours sources → destinations globales.

### État actif KPI
- Indicateur visuel : **souligné** sous le montant (border-bottom `text-gold` ou `text-expense`)
- Couleur montant : `text-gold` pour Entrées, `text-expense` pour Sorties, `text-income` pour Disponible

### Liste catégories — indicateur budget (NOUVEAU)

Chaque ligne catégorie peut avoir un sous-texte budget :

```
[●]  Virements                              -5 513,49 €  ›
     3 263 € au-dessus de l'objectif

[●]  Auto et Transports                     -847,49 €    ›
     203 € restants sur l'objectif
```

- **"X € au-dessus de l'objectif"** → `text-expense` (rouge) — budget dépassé
- **"X € restants sur l'objectif"** → `text-income` (vert) — budget OK, marge restante
- **Aucun texte** (ex: Dépenses exceptionnelles, Inconnu) → pas de `BudgetTarget` défini pour cette catégorie

**Calcul Django :**
```python
# Pour chaque catégorie dans la liste :
target = BudgetTarget.objects.filter(category=cat, period=current_month).first()
actual = Transaction.objects.filter(category=cat, date__range=...).aggregate(Sum('amount_chf'))['total'] or 0

if target:
    delta = abs(actual) - target.amount  # actual est négatif, on compare en absolu
    if delta > 0:
        badge = f"{delta} € au-dessus de l'objectif"   # rouge
    else:
        badge = f"{abs(delta)} € restants sur l'objectif"  # vert
# sinon : pas de badge
```

**Important :** `BudgetTarget.period` = premier jour du mois courant.
Pour une période multi-mois (3M), le budget est comparé mois par mois ou moyenné — à clarifier.

---

### KPIs Row — détail calculs Django
```python
# Entrées
Transaction.objects.filter(
    account__in=selected_accounts,
    date__range=(date_from, date_to),
    is_ignored=False,
    is_internal_transfer=False,
    amount__gt=0
).aggregate(total=Sum('amount_chf'))

# Sorties
# idem avec amount__lt=0

# Disponible = Entrées + Sorties (Sorties est négatif donc addition)

# Dépenses récurrentes
# idem avec is_recurring=True, amount__lt=0
```

---

### Filtre période (1M / 3M / 1A / Custom + ← →)
*Screenshot : `budget_overview_3m_entrées.png` (même écran)*

- Stocké en **session Django** : `request.session['budget_period']` = `'1m'|'3m'|'1a'|'custom'`
- `date_from` / `date_to` calculés côté serveur selon la période active
- Navigation ← → : décale la période (mois suivant / précédent)
- HTMX : changement période → `hx-post` → recharge tout le contenu main (`#budget-content`)

---

### Filtre Sous-catégories (toggle)
*Screenshot : `budget_overview_3m_entrées.png`*

- OFF : Sankey source → catégories (vue actuelle)
- ON : Sankey catégories → sous-catégories (drill-down)
- Stocké en session : `request.session['show_subcategories']`
- HTMX : toggle → recharge le graphique uniquement (`#cashflow-chart`)

---

### Filtres Catégories / Comptes (dropdowns)
*Screenshots : `budget_spec/budget_filter_categories_dropdown.png` + `budget_filter_categories_subcats.png`*

**Comportement confirmé :**
- Retour sur `/budget/` après drill-down catégorie → **session conservée** : période 3M + KPI Sorties toujours actifs ✅
- URL reste `/v2/cashflow` quand le dropdown est ouvert — pas de changement d'URL

**Structure du dropdown "Toutes les catégories" :**
```
[Tout désélectionner]            ← lien reset en haut
─────────────────────
[●] Alimentation et Boissons  ›
[●] Auto et Transports        ›
[●] Besoins essentiels        ›
[●] Dépenses exceptionnelles  ›
[●] Dépenses professionnelles ›
[●] Espèces et Chèques        ›
[●] Factures et Services      ›
[●] Frais                     ›
[●] Impôts                    ›
[●] Inconnu                   ›
[●] Investissements           ›
[●] Loisirs et Divertissements ›
[●] Remboursement emprunt     ›
[●] Remboursements            ›
[●] Revenus                   ›
[●] Santé                     ›
[●] Virements                 ›
```

- `›` chevron à droite → révèle les sous-catégories dans un sous-panneau à droite (nested dropdown)
- Multi-select : toutes cochées par défaut
- **Sélectionnée** : `✓` checkmark à droite + texte `text-text-base`
- **Désélectionnée** : pas de checkmark + texte `text-text-muted` (légèrement grisé)
- **Hovered** : fond `bg-surface-hover/30` + révèle sous-catégories à droite
- `"Tout désélectionner"` en haut → toutes décochées. Devient `"Tout sélectionner"` quand tout est décoché.
- Label du bouton change : `"Toutes les catégories"` (tout coché) → `"X catégories"` (filtre partiel)

**Sous-catégories dans le dropdown :**
- Clic sur `›` d'une catégorie → second panneau qui s'ouvre à droite dans le dropdown
- Même pattern : liste des sous-catégories avec checkbox individuelle
- Permet un filtre très fin : ex. "Alimentation > Courses uniquement"

**Session Django :**
```python
# Stocker les catégories sélectionnées
request.session['budget_selected_categories'] = [1, 3, 5, ...]  # liste d'IDs Category
request.session['budget_selected_accounts'] = [1, 2]            # liste d'IDs Account
# Par défaut : toutes (ne pas stocker = "toutes")
```

**HTMX :** clic checkbox → `hx-post` vers vue budget → recharge `#cashflow-content` (sankey + liste + donut)

*Screenshot confirmé : `budget_spec/budget_filter_categories_deselected.png`*

---

---

---

## NAVIGATION GLOBALE — Flux complet Budget
*Vue d'ensemble de tous les écrans et transitions*

```
/budget/                          ← Page principale
  │
  ├── clic catégorie (›)
  │     └── /budget/category/<id>/      ← Page catégorie (tab Transactions actif par défaut)
  │           ├── [←] back arrow        → /budget/
  │           ├── [▾] category dropdown → /budget/category/<autre_id>/
  │           ├── Tab Transactions      → liste transactions + clic = Détails (right panel)
  │           ├── Tab Sous-catégories   → liste sous-cats + Distribution (right panel)
  │           ├── Tab Objectif          → historique + gauge Objectif (right panel)
  │           └── clic barre Historique → même URL, session updated (mois sélectionné)
  │
  └── bouton "Tout voir"
        └── right panel slide-in       ← liste toutes transactions (reste sur /budget/)
              └── clic transaction     → Détails transaction (right panel, contenu remplacé)
```

**Règle critique :** Les 3 KPIs de la page catégorie (`Transactions` | `Sous-catégories` | `Objectif`) **sont aussi les sélecteurs de tab**. Cliquer le KPI = activer le tab correspondant.

---

## PAGE CATÉGORIE — Drill-down (clic sur une catégorie)
*Screenshot : `budget_spec/budget_category_detail_page.png`*
*Ref Finary : `app.finary.com/v2/cashflow/category/14?type=out`*

### ⚠️ Décision architecture à prendre

Finary navigue vers une **nouvelle page complète** (pas un right panel).
URL : `/v2/cashflow/category/<id>?type=out`

Notre règle "pas d'URL params" = s'applique aux **filtres UI** (période, compte sélectionné) → session Django.
Mais `/budget/category/14/` est une **navigation** = URL Django normale et légitime.

**✅ Décidé (2026-04-06) : Page dédiée comme Finary**
- URL : `/budget/category/<id>/`
- `type` (in/out) → session Django, pas query param
- Back button navigateur fonctionne naturellement

**Le right panel** change de contenu selon le tab actif (pas un slide-in indépendant sur cette page) :
- Tab Transactions + clic transaction → `"Détails de la transaction"`
- Tab Sous-catégories → `"Distribution"` donut
- Tab Objectif → `"Objectif"` gauge

---

### Layout de la page catégorie

```
SIDEBAR  |  MAIN (scroll)  |  OBJECTIF PANEL (fixe droite)
```

- Topbar : `← [●icône] Auto et Transports ▾` — back + nom catégorie + dropdown pour switcher de catégorie
- Right panel fixe : **"Objectif"** (remplace "Distribution" de la page Budget principale)

### Topbar catégorie
*Screenshot : `budget_spec/budget_category_virements_back_arrow.png`*

```
[←]  [●icône]  Virements  [▾]       [1M] [3M●] [1A] [Personnalisé]    [Tous les comptes ▾]
```

- `[←]` : retour `/budget/` — **pas** le back navigateur, un lien Django
- `[●icône] Virements [▾]` : icône catégorie + nom + dropdown pour switcher de catégorie directement
- Filtres période et compte : identiques à la page Budget, synchronisés via session
- **Pas** de dropdown catégories (on est dans une catégorie)

### Sankey catégorie
*Screenshots : `budget_category_virements_tab_transactions.png` + `budget_category_virements_tab_souscategories.png`*

- Source gauche = la catégorie elle-même (100%)
- Destinations droite = **sous-catégories** de cette catégorie avec % et montants
- Ex : `Virements: 2 692 € (100%)` → sous-cats (Virements -2 345 €, Sons -946,83 €, etc.)
- Même Chart.js Sankey, filtré sur 1 catégorie

### KPIs = Sélecteurs de tabs
*Screenshots : tous les tabs*

```
[Transactions]    [Sous-catégories]    [Objectif ✏️]
-2 692 €          6                    9 000 €
```

- **Chaque KPI est cliquable = sélectionne le tab correspondant**
- Tab actif : souligné `border-b border-gold` + valeur en `text-gold`
- `Transactions` : total `Sum(amount_chf)` sur la période
- `Sous-catégories` : `COUNT DISTINCT subcategory_id` sur les transactions filtrées
- `Objectif ✏️` : `BudgetTarget.amount` pour cette catégorie + mois courant. Icône ✏️ = modifier inline

### Tab Transactions (défaut)
*Screenshot : `budget_spec/budget_category_virements_tab_transactions.png`*

- Right panel fixe : **"Détails de la transaction"** quand une transaction est cliquée
- Liste transactions groupées par date (même format que right panel "Tout voir")
- Clic transaction → right panel remplace son contenu avec le détail

**Détail transaction (right panel) :**
```
JEAN MRE, JESSICA, JEROME           -250 €
[● Virements]
Compte         CIC START
Montant        250 €
Date           30/03/2025
[toggle] Inclure dans l'analyse budgétaire  ← is_ignored (inversé)
[toggle] Pointer la transaction             ← is_reconciled
[Modifier la transaction]                   ← ouvre modal/formulaire
```

- Toggle `"Inclure dans l'analyse budgétaire"` = `NOT is_ignored` — OFF = exclure des calculs
- Toggle `"Pointer la transaction"` = `is_reconciled`
- `"Modifier la transaction"` → modal ou page dédiée (Phase 1C)

### Tab Sous-catégories
*Screenshot : `budget_spec/budget_category_virements_tab_souscategories.png`*

- Right panel fixe : **"Distribution"** donut (comme page Budget principale)
- Centre donut : `"Somme totale -2 691,85 €"`
- Liste : sous-catégories avec leurs montants
  ```
  Virements           -2 345 €
  Sons                  -946,83 €
  Transferts internes      -€
  Paiement des loyers      -€
  Transferts internationaux -€
  ```
- Clic sous-catégorie → drill-down ? (à confirmer)

### Tab Objectif
*Screenshots : `budget_spec/budget_category_virements_tab_objectif.png` + `budget_category_objectif_bar_hover.png` + `budget_category_objectif_bar_selected.png`*

- Right panel fixe : **"Objectif"** gauge (semi-cercle doré)
- `[Modifier]` button sur la gauge → inline edit du `BudgetTarget.amount`

**Historique — bar chart mensuel :**
*Screenshots confirmés : `budget_cat_historique_1/2/3.png`*

- 12 mois glissants, une barre par mois
- Ligne pointillée horizontale = `BudgetTarget.amount` — label "OBJECTIF" à droite
- Barre sélectionnée : couleur accent (violet dans Finary, `text-gold` dans BricBudget)
- Barre par défaut = mois courant

**Clic sur une barre — ce qui se met à jour (HTMX partiel) :**
- ✅ KPI `Transactions` → `Sum(amount_chf)` du mois cliqué
- ✅ Stats `"En [mois]"` → transactions count + % dépenses du mois
- ✅ Gauge right panel → `target.amount - abs(spent_this_month)`
- ❌ Sankey → inchangé (période globale)
- ❌ `Sous-catégories` count → inchangé
- ❌ Stats `"12 derniers mois"` → inchangées

**Exemples confirmés (catégorie Loisirs, objectif 3 000 €) :**
| Mois cliqué  | Transactions | Gauge          |
|--------------|-------------|----------------|
| Août 2025    | -1 192 €    | 1 808 € restants |
| Octobre 2025 | -764 €      | 2 236 € restants |
| Janvier 2026 | -2 496 €    | 504 € restants   |

**Django — HTMX ciblé :**
Clic barre → `hx-post` → session `budget_selected_month` → recharge uniquement :
`#cat-kpi-transactions` + `#cat-stats-month` + `#cat-objectif-gauge`

### Historique — bar chart mensuel

```
Chart.js bar chart — 12 mois glissants (AVR → MARS)
```

- Chaque barre = total dépensé ce mois pour cette catégorie
- Barre du mois courant/sélectionné : couleur `text-gold` (mise en avant)
- Autres barres : `bg-surface-hover` grisé
- **Ligne horizontale pointillée dorée** : niveau de l'objectif (`BudgetTarget.amount`)
- Label "OBJECTIF" à droite de la ligne
- Axe Y : en €, auto-scalé
- Axe X : labels mois courts (AVR, MAI, JUIN...)

**Données Django :**
```python
# 12 mois glissants pour cette catégorie
from django.db.models.functions import TruncMonth
Transaction.objects.filter(
    category=cat,
    account__in=selected_accounts,
    is_ignored=False,
).annotate(month=TruncMonth('date')).values('month').annotate(total=Sum('amount_chf')).order_by('month')
```

### Stats en bas — 2 colonnes

**"En [Mois] [Année]" (colonne gauche) :**
- `Transactions : 21` — count transactions ce mois
- `% dépenses : 7%` — part de cette catégorie dans le total dépenses du mois (avec arc circulaire)

**"12 derniers mois" (colonne droite) :**
- `Dépenses moyennes : 666 € en moyenne` (ⓘ tooltip)
- `Meilleure série : 1 mois` — nb mois consécutifs sous l'objectif
- `% dépenses (année en cours) : 13%` (ⓘ)
- `Dépassement d'objectif (%) : 83%` — % des mois où l'objectif a été dépassé

**Note :** ces stats sont des **analytics avancées** — à implémenter en Phase 3B, pas en Phase 2.

### Right panel fixe — Objectif

Remplace le donut "Distribution" de la page Budget principale.

```
OBJECTIF
Objectif    1 050 €                    [Modifier]

    ╭────────────────╮
   ╱    203 €         ╲
  │  Restants sur      │
  │   l'objectif       │
   ╲                  ╱
    ╰────────────────╯
```

- Semi-cercle (gauge) en `text-gold` — arc proportionnel à (dépensé / objectif)
- Centre : montant restant (ou dépassement si > objectif)
- Sous-texte : "Restants sur l'objectif" (vert) ou "Au-dessus de l'objectif" (rouge)
- Bouton `Modifier` → modal ou inline edit pour changer le `BudgetTarget.amount`

**Calcul :**
```python
target = BudgetTarget.objects.filter(category=cat, period=first_of_month).first()
spent = abs(Transaction.objects.filter(category=cat, date__month=...).aggregate(Sum('amount_chf'))['total'] or 0)
remaining = target.amount - spent  # positif = restant, négatif = dépassement
arc_pct = min(spent / target.amount, 1.0)  # 0→1 pour l'arc
```

---

### Right panel — liste transactions (bouton "Tout voir")
*Screenshots : `budget_spec/budget_rightpanel_transactions_list.png` + `budget_rightpanel_transactions_filter.png`*

**Déclencheur :** clic `Tout voir` sous les KPIs. URL reste `/budget/` — slide-in, pas navigation.
**Width BricBudget : 520px** (Finary ~420px — Emmanuel veut plus large)

**Header du panel :**
```
Liste des transactions                                    [X]
[1 févr. 2026 - 30 avr. 2026]   [1M] [3M●] [Personnalisé]
[🔍 Trouver une transaction                              ]
[Afficher les filtres]
```

- Titre : `"Liste des transactions"` + `[X]` ferme le panel
- Période : héritée de la session Budget — **synchronisée**
- Barre recherche : filtre live sur `merchant_name` + `description_raw`
- Bouton `"Afficher les filtres"` : toggle. Couleur `text-gold` / `border-gold` quand filtres actifs

**Filtres dépliés (toggle → `"Masquer les filtres"`) :**
```
[Tous les montants ▾]  [Tous les comptes ▾]  [X catégories ▾]  [Toutes les transactions ▾]
```
- `Tous les montants` → **2 sections** :
  - Type : `Tout ✓` / `Revenus` / `Dépenses`
  - Range montant : `Inférieur ou égal à` / `Supérieur ou égal à` / `Égal à (=)` + champ `Montant`
- `Tous les comptes` → multi-select comptes (indépendant du filtre Budget)
- `X catégories` → hérite du filtre actif de la page Budget
- `Toutes les transactions` → **3 options** (radio) : `Toutes les transactions ✓` / `Pointées uniquement` / `Non pointées uniquement`

**Rows — liste verticale (pas un tableau) :**

Groupée par type avec headers de section (`VIREMENTS`, `CREDIT`, etc.)

Groupée par **date** (pas par type) :

```
─ 17 Mars 2026 ──────────────────────────────────────────────────
[●]  MONTBONNOT S...                  [● CIC START]  -12 €    [□]
     Snacks · 19,05 CHF AVEC...
─ 01 Mars 2026 ──────────────────────────────────────────────────
[●]  ST ISMER ORIAD...                [● CIC START]  -21,03 € [□]
     Alimentation et Boiss... · 19,05 CHF AVEC...
[●]  20,40 CHF RAJA...                [● CIC START]  -22,52 € [□]
     Alimentation et Boiss...
```

- **Groupes = dates** (JJ Mois AAAA), pas par type de transaction
- Icône catégorie : cercle coloré à gauche
- Ligne 1 : `merchant_name` (bold, tronqué)
- Ligne 2 : `subcategory.name` + `description_raw` partiel + montant devise native (CHF si compte CHF)
- Badge compte : `[● dot] account.name` — **à remplacer par icône banque SVG**
- Montant principal : `text-income` / `text-expense`, aligné à droite
- **Checkbox `[□]` à DROITE** de chaque ligne — confirme multi-select ✅

**Multi-select (confirmé Finary + voulu par Emmanuel) :**
- Checkbox à droite de chaque row — visible en permanence (pas seulement au hover)
- Sélection multiple → action groupée (pointer, ignorer, catégoriser)
- BricBudget : barre contextuelle en bas du panel quand ≥1 sélectionné :
  `"X transactions sélectionnées  [Pointer] [Ignorer] [Catégoriser]"`
- HTMX : `hx-post` bulk update → `is_reconciled` / `is_ignored`

**Badge compte — implémentation BricBudget :**
```html
<span class="flex items-center gap-1 text-text-muted text-xs">
  <img src="{% static 'icons/banks/'|add:tx.account.bank.icon_slug|add:'.svg' %}" class="w-4 h-4">
  {{ tx.account.name }}
</span>
```
- Tous cochés par défaut (pas de filtrage)
- Changement de filtre → recharge la liste transactions (`hx-post`)

---

### Right panel — sélection et actions bulk
*Screenshot : `budget_spec/budget_rightpanel_transactions_list.png`*

**Checkbox sélection :**
- Left column de chaque ligne
- Permet de sélectionner plusieurs transactions
- Header row a une checkbox "select all" (toutes visibles)

**Barre d'actions (révélée après sélection) :**
```
[X transactions sélectionnées]  [✓ Pointer] [⊘ Ignorer] [⟲ Lier virements] [⋯ Plus]
```

- Texte dynamique : "3 transactions sélectionnées"
- **`✓ Pointer`** : `is_reconciled = True` pour toutes les sélectionnées
- **`⊘ Ignorer`** : `is_ignored = True`
- **`⟲ Lier virements`** : sélectionner 2 transactions, créer `paired_transaction` (virement interne)
- **`⋯ Plus`** : dropdown avec actions supplémentaires (assigner catégorie bulk, ajouter note, etc.)
- Actions HTMX → recharge la liste après modification

**État aucune sélection :**
Barre d'actions masquée.

---

### Right panel — width + contenu
*Design note (2026-04-06)*

**Width du panel :**
- Actuel (Finary) : ~380px (tight)
- Demandé : "un peu plus gros" — 480px? 520px?
- À décider avec Emmanuel selon l'espace disponible (dépend du layout 3-colonnes)

**Infos à ajouter au tableau transactions :**
- Plus de colonnes ? Plus grand les textes existants ? A clarifier.

---

### Logo du compte (icône banque)
*À intégrer à la colonne "Compte"*

**Actuellement :** "Yuh", "UBS", "CIC" en texte
**À ajouter :** icône banque + label texte

```
[Yuh icon] Yuh        ← icône + label
[UBS icon] UBS
[CIC icon] CIC
```

- Icône : `static/icons/banks/<bank.icon_slug>.svg`, ~20px
- Label : `account.bank.name` ou `account.name` ?
- Cliquable ? Filtre par compte dans le panel ? À confirmer.

---

### Classification automatique (UI à définir)
*Nouveau composant — à documenter*

**Contexte :** Finary a une UI pour catégoriser automatiquement des transactions.
**Questions :**
- C'est une modal ? Un panel side dropdown ? Un inline edit dans le tableau ?
- Est-ce qu'il y a un screen Finary à analyser ?
- Ou c'est une feature pour plus tard (Phase 1C ?) ?
- Logique : utilisateur sélectionne transactions → "Catégoriser automatiquement" → Claude API ou CategorizationRule appliquées ?

**À noter dans une nouvelle section une fois le design clarifié.**

---

## ARCHITECTURE DJANGO — Page Budget

### URLs

```python
path('budget/', views.budget, name='budget'),
path('budget/category/<int:pk>/', views.budget_category, name='budget_category'),
```

### Session state (toutes les clés)

```python
request.session['budget_period']            = '1m' | '3m' | '1a' | 'custom'
request.session['budget_date_from']         = '2026-02-01'
request.session['budget_date_to']           = '2026-04-30'
request.session['budget_selected_accounts'] = [1, 2, 3]     # IDs Account
request.session['budget_selected_cats']     = [1, 3, 5]     # IDs Category (None = toutes)
request.session['budget_active_kpi']        = 'out'          # 'in' | 'out' | 'available' | 'recurring'
request.session['budget_show_subcats']      = False
request.session['budget_cat_tab']           = 'transactions'  # 'transactions' | 'subcategories' | 'objectif'
request.session['budget_selected_month']    = '2025-08-01'   # barre historique cliquée
```

---

## CHALLENGE DB & MODÈLES

### ✅ Ce qui est bon

- `BudgetTarget(category, period, amount)` — objectifs différents par mois, historique préservé
- `Transaction.is_ignored` / `is_reconciled` / `is_internal_transfer` — tous les toggles UI ont leur champ
- `Transaction.amount_chf` — consolidation multi-devises prévue

### ⚠️ À challenger

**1. Index manquant sur Transaction**
```python
# transactions/models.py — à ajouter dans Meta
class Meta:
    indexes = [
        models.Index(fields=['category', 'date']),
        models.Index(fields=['account', 'date']),
    ]
```
Historique 12 mois × N catégories = lent sans index.

**2. Stats historique — tout calculable, pas de nouveau modèle**
```python
avg = sum(abs(m['total']) for m in historique) / len(historique)
exceeded_pct = sum(1 for m in historique if abs(m['total']) > target.amount) / 12 * 100
```

**3. `Transaction.subcategory` null → filtrer pour le count**
```python
subcat_count = qs.exclude(subcategory=None).values('subcategory_id').distinct().count()
```

**4. Pas d'app `budget/` séparée pour l'instant** — tout dans `transactions/views.py`. Extraire si Phase 3+ devient ingérable.

---

## PLANNING BUDGET — Phases d'implémentation

### Phase 2A — Page Budget principale
- Sankey Chart.js + plugin `chartjs-chart-sankey`
- KPIs row + clic KPI filtre liste
- Liste catégories + badge budget rouge/vert
- Distribution donut (right panel fixe)
- Filtres période + catégories + comptes (session)
- Toggle Sous-catégories

### Phase 2B — Page catégorie, Tab Transactions
- `/budget/category/<id>/`
- Topbar : back `←` + category dropdown `▾`
- Sankey catégorie (→ sous-catégories)
- KPIs = tab selectors
- Liste transactions + Détails transaction (right panel)
- Toggles `is_reconciled` + `is_ignored` HTMX

### Phase 2C — Objectifs + Historique
- Tab Objectif : gauge semi-cercle
- Bar chart historique 12 mois + ligne objectif
- Clic barre → session `budget_selected_month` → stats + gauge mis à jour
- Modifier objectif inline (HTMX → BudgetTarget upsert)

### Phase 2D — Sous-catégories + Multi-select
- Tab Sous-catégories + Distribution donut
- Multi-select transactions → barre contextuelle (Pointer / Ignorer / Catégoriser)
- Panel "Tout voir" complet avec tous les filtres
- Right panel "Modifier la transaction"

---

---

## FLOW CATÉGORISATION — Modifier catégorie + Créer règle
*Screenshots : `assets/private/references/budget_spec/categorization/cat_flow_01` → `cat_flow_11`*
*Analysé le 2026-04-06 — flux complet en 11 étapes*

---

### Vue d'ensemble du flux

```
Budget page
    │
    ├─ [Tout voir] ──────────────────────────────────────────────────────────────┐
    │                                                                             │
    │                                           RIGHT PANEL "Liste des transactions"
    │                                               │
    │                                               ▼ clic sur une transaction
    │                                           RIGHT PANEL "Modifier la catégorie"
    │                                               │
    │                                               ▼ sélection catégorie/sous-catégorie
    │                                           Toast vert "Catégorie modifiée"
    │                                           + CTA "Créer une règle" (countdown ~5s)
    │                                               │
    │                               ┌──── Ignorer ─┘─── Clic "Créer une règle" ────┐
    │                               │                                               │
    │                               │                             Modale Step 1 : transactions similaires
    │                               │                             Modale Step 2 : token chips + live preview
    │                               │                             Modale Step 3 : confirmation + count
    │                               │                                               │
    │                               └───────────────────────────────────────────────┤
    │                                                                               │
    │                                           RIGHT PANEL "Liste des transactions"
    │                                           + Toast "Règle créée"
    └────────────────────────────────────────────────────────────────────────────────
```

---

### ÉTAPE 1 — Right panel : Liste des transactions
*Screenshot : `cat_flow_02_tout_voir_rightpanel.png`*

Déclenché par clic "Tout voir" sur une catégorie depuis la vue Budget.

**Structure du right panel :**
```
┌─────────────────────────────────────┐
│ Liste des transactions          [✕] │
│                                     │
│ [1 janv. 2026 - 31 janv. 2026 ▾]   │
│                        Sélectionner │
│                         tout(es)    │
├─────────────────────────────────────┤
│ — date group header —               │
│ [●] MONTBONNOT S.  CIC START  23.8€ │
│ [●] 4.10 CHF AGRI... CIC START  0€  │
│ [●] ORGILLES PRAIRI... CIC  8.90€   │
│ [●] CHAMBERY NSK  CIC START   -19€  │
│ — date group header —               │
│ [●] TLAT CHF AGRI... CIC  60.59€    │
│ ...                                 │
└─────────────────────────────────────┘
```

**Tags banque :** badge "CIC START", "YUH", etc. = `account.bank_name + account.name`

**Sélection multiple :** "Sélectionner tout(es)" → checkbox header (Phase 2D)

**HTMX trigger :** `hx-get="/budget/panel/transactions/?category_id=X"` → remplace `#right-panel-content`

---

### ÉTAPE 2 — Right panel : Modifier la catégorie (picker)
*Screenshot : `cat_flow_03_transaction_detail.png`*

Déclenché par clic sur une transaction dans la liste.

**Structure :**
```
┌─────────────────────────────────────┐
│ Modifier la catégorie           [✕] │
├─────────────────────────────────────┤
│ [toggle] Règle intelligente         │
│          automatique                │
│ "Utilisez nos modèle automatique    │
│  "TABAC". La mise à jour nouvelle   │
│  catégorie remplacera la règle      │
│  intelligente pour cette transaction│
├─────────────────────────────────────┤
│ [🔍 Rechercher des catégories...  ] │
│ [+ Créer une catégorie personnalisée│
├─────────────────────────────────────┤
│ Catégories personnalisées           │
│   [●] Dépenses exceptionnelles  [>] │
│                                     │
│ Catégories                          │
│   [●] Alimentation et Boissons  [>] │
│   [●] Auto et Transports        [>] │
│   [●] Besoins essentiels        [>] │
│   [●] Dépenses professionnelles [>] │
│   [●] Épargne et Chèques        [>] │
│   [●] Factures et Services      [>] │
│   [●] Frais                     [>] │
│   [●] Impôts                    [>] │
│   [●] Income                    [>] │
│   [●] Investissements           [>] │
│   [●] Loisirs et Divertissements[>] │
│   [●] Remboursement emprunt     [>] │
│   ...                               │
└─────────────────────────────────────┘
```

**Section "Règle intelligente automatique" :**
- Toggle ON/OFF
- Quand ON : affiche la catégorie suggérée par l'IA (Phase 6 — placer le toggle dès Phase 2B, désactivé/vide pour l'instant)
- Texte d'info contextuel lié à la suggestion en cours
- Pour BricBudget Phase 2B : toggle visible mais désactivé + texte "Classification automatique disponible en Phase 6"

**Deux sections dans la liste :**
1. "Catégories personnalisées" — catégories créées par l'utilisateur (`is_system=False`)
2. "Catégories" — catégories système (`is_system=True`)

**Queryset Django :**
```python
# Catégories actives, séparées en deux groupes
system = Category.objects.filter(is_active=True, is_system=True).order_by('order')
custom = Category.objects.filter(is_active=True, is_system=False).order_by('order')
```

**HTMX trigger :** `hx-get="/budget/panel/category-picker/?tx_id=X"` → remplace `#right-panel-content`

---

### ÉTAPE 3 — Right panel : Accordion sous-catégories
*Screenshot : `cat_flow_04_category_picker_open.png`*

Déclenché par clic sur `[>]` d'une catégorie dans la liste.

**Comportement :**
- La catégorie cliquée s'étend en accordéon INLINE (pas de navigation)
- Les sous-catégories apparaissent dessous, indentées
- Une seule catégorie peut être ouverte à la fois (ferme l'autre si déjà ouverte)
- La sous-catégorie hover/sélectionnée est highlightée en `bg-gold/10 text-gold`

**Structure expandée :**
```
│   [●] Auto et Transports        [▲] ← chevron retourné, fond gold/10
│       [●] Amendes                   │
│       [●] Location de voiture       │ sous-catégories
│       [●] Lavage                    │ indentées
│       [●] Carburant                 │
│       [●] Nourriture           ← hover/selected │
│       [●] Parking                   │
│       [●] Billets d'avion           │
│       [●] Transports publics        │
│       [●] Réparations               │
│       [●] Vélos VTT et Consomm.     │
```

**HTMX toggle accordion :**
- `hx-get="/budget/panel/category-picker/subcats/?cat_id=X"` → injecte les sous-catégories inline
- Ou géré en CSS pur avec `<details>/<summary>` si pas d'état serveur nécessaire

**Clic sur sous-catégorie :**
- POST HTMX → `Transaction.category = cat, Transaction.subcategory = subcat`
- → right panel remplace le picker par la liste des transactions
- → déclenche le toast de confirmation

---

### ÉTAPE 4 — Toast "Catégorie modifiée" + CTA règle
*Screenshot : `cat_flow_05_category_assigned_toast.png`*

**Apparaît après l'assignation de catégorie.**

**Structure visuelle (overlay en haut à droite, au-dessus du right panel) :**
```
┌─────────────────────────────────────────────┐
│ ✅ Catégorie modifiée                        │
│    La transaction "MONTBONNOT ST..." a été  │
│    classée en Tabac.                         │
│                                              │
│    [Créer une règle automatique →]  [5s...] │
└─────────────────────────────────────────────┘
```

**Comportement :**
- Le right panel revient à la liste des transactions (fond visible)
- Le toast apparaît PAR-DESSUS (z-index supérieur)
- Countdown visuel ~5 secondes, puis disparaît automatiquement
- Si l'utilisateur clique "Créer une règle" : déclenche le wizard
- Si ignoré / countdown terminé : toast disparaît, fin du flux

**Implémentation BricBudget :**
- Le toast est en JavaScript pur (pas HTMX) : affiché après le succès de la requête HTMX
- `htmx:afterRequest` → JS affiche le toast + setTimeout(hideToast, 5000)
- Le CTA "Créer une règle" ouvre la modale wizard avec `tx_id` et `category_id` en params

---

### ÉTAPE 5 — Wizard Step 1 : Transactions similaires
*Screenshot : `cat_flow_06_rule_similar_transactions.png`*

**Modale plein écran assombri (pas un right panel — overlay central).**

```
┌─────────────────────────────────────┐
│ ✨ RÈGLE INTELLIGENTE               │
│                                [✕] │
│ Appliquer Tabac aux                 │
│ transactions similaires             │
│                                     │
│ Créez des règles basées sur le nom  │
│ des transactions pour re-catégoriser│
│ automatiquement les transactions    │
│ passées et futures.                 │
│                                     │
│ [●] MONTBONNOT ST TABAC PRESSE  12€ │
│                                     │
│ [Plus tard]          [Suivant >]    │
└─────────────────────────────────────┘
```

**Ce que Finary fait :**
- Prend le `description_raw` de la transaction qu'on vient de catégoriser
- Cherche en DB les autres transactions avec une description similaire (même premier token ?)
- Affiche le compte + l'exemple le plus récent

**Ce que BricBudget fera :**
- Prend les tokens de `description_raw.upper().split()`
- `Transaction.objects.filter(description_raw__icontains=tokens[0]).exclude(id=tx_id).count()`
- Affiche le count + un exemple

**"Plus tard"** → ferme la modale, fin du flux
**"Suivant >"** → Step 2

---

### ÉTAPE 6 — Wizard Step 2 : Sélection de tokens (keyword chips)
*Screenshots : `cat_flow_07_rule_keyword_tokens.png`, `cat_flow_08_rule_keyword_montbonnot_preview.png`, `cat_flow_09_rule_keywords_final_selection.png`*

**C'est l'étape clé du wizard.**

```
┌─────────────────────────────────────────────────┐
│ Nouvelle règle pour Tabac:                  [✕] │
│                                                  │
│ Sélectionnez le(s) mot-clé(s) à rechercher     │
│ pour re-catégoriser vos 9 transactions dans     │
│ Tabac:                                          │
│                                                  │
│  [MONTBONNOT]  [ST]  [TABAC]  [PRESSE]          │
│  ← chips cliquables, toggle on/off              │
│                                                  │
│ Les X transactions ci-dessous seront            │
│ catégorisées en Tabac.                          │
│                                                  │
│ ┌──────────────────────────────────┐            │
│ │ date | description | montant     │            │
│ │ ...                              │            │
│ │ (liste live — se met à jour      │            │
│ │  à chaque clic sur un chip)      │            │
│ └──────────────────────────────────┘            │
│                                                  │
│                          [Suivant >]            │
└─────────────────────────────────────────────────┘
```

**Algorithme de génération des tokens :**
```python
# transactions/services.py — à ajouter : RuleWizardService.extract_tokens()
def extract_tokens(description_raw: str) -> list[str]:
    """
    Splitte description_raw en tokens significatifs pour le wizard de règle.
    Filtre les tokens trop courts ou purement numériques.
    Conserve l'UPPERCASE (important : les descriptions bancaires sont tout en majuscules).

    Exemple : "MONTBONNOT ST TABAC PRESSE"
    → ["MONTBONNOT", "ST", "TABAC", "PRESSE"]
    """
    tokens = description_raw.upper().split()
    # Exclure tokens trop courts (1 char) ou purement numériques
    return [t for t in tokens if len(t) > 1 and not t.replace('.', '').replace(',', '').isdigit()]
```

**Logique de matching (IMPORTANT) :**

Les tokens sélectionnés sont **concaténés avec espace** pour former un seul keyword :
```
["MONTBONNOT", "ST", "TABAC"] → keyword = "MONTBONNOT ST TABAC"
```

Ce keyword est ensuite utilisé comme substring :
```python
Transaction.objects.filter(description_raw__icontains="MONTBONNOT ST TABAC")
# → matche "MONTBONNOT ST TABAC PRESSE" ✅
# → matche "MONTBONNOT SA TABAC" ✗ (substring "MONTBONNOT ST TABAC" absent)
```

La liste de preview se met à jour en **temps réel** à chaque toggle de chip :
- HTMX `hx-trigger="click"` sur chaque chip
- POST → `GET /budget/rules/wizard/preview/?tokens=MONTBONNOT+ST+TABAC&category_id=X`
- Réponse = partial HTML de la liste transactions correspondantes + count

**État des chips :**
- Chip sélectionné : `bg-gold text-black font-semibold` (pill pleine)
- Chip non-sélectionné : `bg-surface-3 text-text-muted border border-edge` (pill vide)

**État de la liste :**
- 0 chip sélectionné → "Aucune transaction ne sera recatégorisée"
- 1+ chips → liste transactions + count "Les X transactions ci-dessous..."

---

### ÉTAPE 7 — Wizard Step 3 : Confirmation
*Screenshot : `cat_flow_10_rule_impact_summary.png`*

```
┌─────────────────────────────────────────────┐
│ ✨ CRÉER RÈGLE INTELLIGENTE                  │
│                                         [✕] │
│ Confirmer le changement de catégorie        │
│                                             │
│ Cette règle recatégorise automatiquement    │
│ 36 transactions en Tabac. Elles seront      │
│ recatégorisées et les nouvelles transactions│
│ seront basées sur cette règle appliquée     │
│ automatiquement.                            │
│                                             │
│ MONTBONNOT ST TABAC                         │
│ ← le keyword final (affiché tel quel)      │
│                                             │
│ Il faudra créer une nouvelle règle pour     │
│ créer sa règle nommer.                      │
│                                             │
│                          [Confirmer]        │
└─────────────────────────────────────────────┘
```

**Ce que "Confirmer" déclenche :**
```python
# 1. Créer la règle en DB
rule = CategorizationRule.objects.create(
    keyword="MONTBONNOT ST TABAC",
    target_field=CategorizationRule.TargetField.DESCRIPTION_RAW,
    category=category,
    subcategory=subcategory,
    priority=10,   # priorité par défaut pour les règles créées via wizard
    is_active=True,
)

# 2. Recatégoriser toutes les transactions matchantes (bulk update)
# NB : on écrase uniquement les transactions NON manuellement catégorisées
Transaction.objects.filter(
    description_raw__icontains=rule.keyword,
).exclude(
    categorization_source=Transaction.CategorizationSource.MANUAL
).update(
    category=rule.category,
    subcategory=rule.subcategory,
    categorization_source=Transaction.CategorizationSource.RULE,
    categorization_rule=rule,
)
```

**Point critique :** le bulk update ne doit PAS écraser les transactions catégorisées manuellement (`categorization_source=MANUAL`). L'utilisateur a pris une décision explicite pour celles-là.

---

### ÉTAPE 8 — Toast final "Règle créée"
*Screenshot : `cat_flow_11_rule_confirmed.png`*

```
┌─────────────────────────────────────────────┐
│ Nouvelle règle intelligente créée.          │
│ Toutes les transactions contenant les mots  │
│ "MONTBONNOT", "ST", "TABAC" seront          │
│ catégorisées en Tabac.                      │
└─────────────────────────────────────────────┘
```

- Right panel revient à la liste des transactions (mise à jour via HTMX)
- Toast apparaît par-dessus, disparaît après ~4s
- La transaction qu'on avait cliquée apparaît maintenant avec sa nouvelle catégorie

---

## ARCHITECTURE RIGHT PANEL — États multiples

Le right panel est **multiplexé** : un seul élément `#right-panel`, contenu rechargé par HTMX.

```
#right-panel (aside fixe droite)  ← défini dans base_app.html
    ├── header (flex px-5 py-4)   ← défini dans right_panel.html
    │       label "Détail"  +  [✕]
    │       ⚠️  label hardcodé "Détail" — à rendre dynamique (voir challenge #7)
    │
    └── #panel-content            ← id réel dans right_panel.html (pas right-panel-content)
            │
            ├── [état A] _panel_tx_list.html
            │       "Liste des transactions" — Tout voir
            │
            ├── [état B] _panel_category_picker.html
            │       "Modifier la catégorie" — picker categories + sous-cats
            │
            └── [état C] _panel_tx_detail.html
                    "Détail transaction" — readonly (Phase 2B)
```

**Les modales wizard** (Steps 1-3) ne sont PAS dans le right panel — ce sont des overlays
séparés, affichés par-dessus tout (`z-50`), déclenchés depuis le toast JS.

**URLs :**
```
GET  /budget/panel/transactions/?category_id=X         → état A  → target #panel-content
GET  /budget/panel/category-picker/?tx_id=X            → état B  → target #panel-content
GET  /budget/panel/tx-detail/?tx_id=X                  → état C  → target #panel-content
POST /budget/transactions/categorize/                   → assign catégorie + réponse HTMX
GET  /budget/rules/wizard/preview/?tokens=X&cat_id=Y   → partial liste preview (wizard step 2)
POST /budget/rules/wizard/confirm/                      → create rule + bulk update
```

---

## CHALLENGES AU CODE ACTUEL

### 1. `target_field` défaut : `merchant_name` → à remettre en question

Notre `CategorizationRule.target_field` défaut est `merchant_name`.
Mais le wizard Finary tokenise `description_raw`.

**Décision à prendre :**
- Les règles créées **via wizard** → `target_field=DESCRIPTION_RAW` (tokens extraits du raw)
- Les règles créées **manuellement** (si on ajoute un écran "Paramètres Règles") → `target_field=MERCHANT_NAME` (l'utilisateur tape le nom du marchand nettoyé)

Action : le wizard doit forcer `target_field=DESCRIPTION_RAW` à la création.

### 2. `CategorizationRule.keyword` : unicité ?

Pas de `unique_together` sur `(keyword, category)`.
Risque : l'utilisateur crée deux fois la même règle par inadvertance.

**À challenger :** ajouter `unique_together = [("keyword", "target_field")]` en migration ?
Ou au moins une validation dans le wizard ("cette règle existe déjà").

### 3. Bulk update exclut les transactions manuelles — mais pas l'import futur

Le bulk update exclut `categorization_source=MANUAL`. Correct.
Mais lors des imports futurs, `_find_rule()` applique toutes les règles actives indifféremment.
**Problème :** si l'utilisateur a manuellement recatégorisé une transaction avec `MONTBONNOT ST TABAC` dans une autre catégorie, le prochain import d'une transaction similaire appliquera quand même la règle.

C'est le comportement correct pour les nouvelles transactions (la règle doit s'appliquer).
Pour les transactions existantes, le `exclude(MANUAL)` protège. Cohérent ✅.

### 4. Index DB manquant (déjà noté)

```python
# Le preview wizard fait :
Transaction.objects.filter(description_raw__icontains="MONTBONNOT ST TABAC")
# → full-text scan sur description_raw sans index → lent sur > 5000 transactions
```

**Solution :** `GinIndex` PostgreSQL sur `description_raw` pour le full-text search.
```python
# transactions/models.py → Meta.indexes
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector

indexes = [
    GinIndex(fields=['description_raw'], name='tx_desc_gin'),  # Phase 2E
    models.Index(fields=['category', 'date']),
    models.Index(fields=['account', 'date']),
]
```
Pour Phase 2B, `icontains` suffit (< 2000 transactions en prod initiale). Ajouter le GinIndex en Phase 2E si perfs dégradent.

### 5. Token extraction : pas encore de service

`RuleWizardService.extract_tokens(description_raw)` à créer dans `transactions/services.py`.
Actuellement absent. Bloquant pour le wizard.

### 6. Le right panel utilise `#panel-content`, pas `#right-panel-content`

Confirmé en lisant `right_panel.html` : la div rechargeable s'appelle `#panel-content`.
Toutes les requêtes HTMX doivent cibler `hx-target="#panel-content"`. ✅ Aucun changement d'ID nécessaire.

### 7. Header du right panel hardcodé "Détail"

`right_panel.html` ligne 20 : `<span>Détail</span>` — hardcodé.
Mais selon le contexte, le titre devrait changer :
- État A : "Liste des transactions"
- État B : "Modifier la catégorie"
- État C : "Détail"

**Solution :** inclure le header DANS chaque partial (pas dans `right_panel.html`).
Retirer le header de `right_panel.html`, et laisser chaque `_panel_*.html` définir son propre header.
`right_panel.html` ne contient alors que le `#panel-content` vide + la logique fermeture.

⚠️ **Bloquant pour Phase 2B** — à corriger avant de coder le first panel.

---

## ORGANISATION DES SCREENSHOTS — Structure sous-dossiers

```
assets/private/references/
├── finary_screenshot/          ← anciens screenshots numérotés 01-27
├── budget_spec/
│   ├── *.png                   ← screenshots vue Budget général + filtres + catégories
│   └── categorization/         ← flow complet catégorisation + wizard règle
│       ├── cat_flow_01_budget_overview.png
│       ├── cat_flow_02_tout_voir_rightpanel.png
│       ├── cat_flow_03_transaction_detail.png
│       ├── cat_flow_04_category_picker_open.png
│       ├── cat_flow_05_category_assigned_toast.png
│       ├── cat_flow_06_rule_similar_transactions.png
│       ├── cat_flow_07_rule_keyword_tokens.png
│       ├── cat_flow_08_rule_keyword_montbonnot_preview.png
│       ├── cat_flow_09_rule_keywords_final_selection.png
│       ├── cat_flow_10_rule_impact_summary.png
│       └── cat_flow_11_rule_confirmed.png
```

**Prochains sous-dossiers à créer selon besoin :**
- `budget_spec/parameters/` — écran Paramètres catégories + gestion règles
- `budget_spec/transactions/` — vue Transactions, filtres, badges carte

---

## PLANNING CLASSIFICATION — Phases d'implémentation

### Phase 2B (dans la page catégorie)
- Right panel état B : `right_panel_category_picker.html`
  - Liste catégories scrollable, accordion pour les sous-catégories
  - Toggle "IA" placeholder (désactivé, texte "Phase 6")
  - POST HTMX → assign category/subcategory + toast JS

### Phase 2E — Wizard de règle (après Phase 2D)
- Toast "Catégorie modifiée" + CTA "Créer une règle"
- `RuleWizardService.extract_tokens()` dans `services.py`
- Modale Step 1 : transactions similaires (count + exemple)
- Modale Step 2 : chips HTMX + live preview (partial)
- Modale Step 3 : confirmation + bulk update
- Toast final "Règle créée"
- URL `/budget/rules/wizard/` (GET step, POST confirm)

### Phase 3A — Page Paramètres Règles
- Liste de toutes les `CategorizationRule` actives
- Créer / modifier / désactiver une règle manuellement
- Bouton "Appliquer à toutes les transactions" par règle
- Bouton "Paramètres" dans le topbar Budget → `/settings/rules/`

---

---

## DÉTAIL TRANSACTION — Right panel état C
*Screenshot : `budget_spec/category_page/budget_category_virements_tab_transactions.png`*
*Déclenché par clic sur une ligne dans la liste transactions (tab Transactions page catégorie)*

```
┌─────────────────────────────────────────┐
│ Détails de la transaction           [✕] │
├─────────────────────────────────────────┤
│ SEBA MRS JESSICA JENNING               │  ← merchant_name (ou description_raw tronquée)
│                                         │
│ -250 €                                  │  ← amount (négatif = dépense, en gros)
│                                         │
│ [●] Virements              [>]          │  ← category badge + arrow (cliquable = ouvre picker)
│                                         │
│ Compte       CIC START                  │
│ Montant      236 €                      │  ← amount_chf si devise ≠ CHF
│ Date         02/01/2031                 │  ← transaction.date
│                                         │
│ Exclure l'analyse budgétaire    [toggle]│  ← NOT is_ignored (toggle ON = inclus = is_ignored False)
│ Pointer la transaction          [toggle]│  ← is_reconciled
│                                         │
│         [Modifier la transaction]       │  ← ouvre l'éditeur complet (Phase 2D)
└─────────────────────────────────────────┘
```

**Champs affichés :**
| Champ UI | Modèle Django | Note |
|----------|---------------|------|
| Nom transaction | `merchant_name` ou `description_raw[:50]` | |
| Montant principal | `amount` + `currency` | négatif = dépense |
| Catégorie badge | `category.name` + `category.colour_hex` | cliquable → ouvre picker |
| Compte | `account.name` | |
| Montant CHF | `amount_chf` | affiché uniquement si `currency != "CHF"` |
| Date | `date` | format DD/MM/YYYY |
| Exclure analyse | `NOT is_ignored` | toggle HTMX → PATCH |
| Pointer | `is_reconciled` | toggle HTMX → PATCH |

**Comportement du badge catégorie [>] :**
- Clic → same right panel remplace l'état C par l'état B (category picker)
- Retour possible via back arrow dans le picker (ou fermeture)

**HTMX :**
```
GET  /budget/panel/tx-detail/?tx_id=X           → target #panel-content
POST /budget/transactions/X/toggle-ignored/     → HTMX swap toggle uniquement
POST /budget/transactions/X/toggle-reconciled/  → HTMX swap toggle uniquement
```

---

## STATISTIQUES HISTORIQUE — Section détaillée
*Screenshots : `budget_spec/category_page/budget_cat_historique_1-3.png`*
*Visible sous le bar chart quand tab Objectif actif (page catégorie)*

Deux blocs de stats côte à côte, qui SE METTENT À JOUR quand on clique une barre :

### Bloc gauche — "En [Mois sélectionné]"
```
En Août 2025
┌──────────────────┬─────────────────────────────────┐
│ 16               │ 1975 € en moyenne                │
│ transactions     │                                  │
├──────────────────┼─────────────────────────────────┤
│ 80 %  [ℹ️]      │ 4 mois                           │
│ récurrences      │ dépassement objectif             │
└──────────────────┴─────────────────────────────────┘
```

**Données Django (pour le mois sélectionné = `session["budget_selected_month"]`) :**
```python
month_qs = Transaction.objects.filter(
    category=category,
    date__year=selected_month.year,
    date__month=selected_month.month,
    is_ignored=False,
)
tx_count      = month_qs.count()
avg_amount    = month_qs.aggregate(avg=Avg('amount_chf'))['avg']
recurring_pct = month_qs.filter(is_recurring=True).count() / tx_count * 100
```

### Bloc droit — "12 derniers mois"
```
12 derniers mois
┌──────────────────┬─────────────────────────────────┐
│ 1975 € en moy.   │ 16 %  [ℹ️]                      │
│                  │ récurrences                      │
├──────────────────┼─────────────────────────────────┤
│ 4 mois           │ 42 %                             │
│ historique       │ dépassement objectif             │
└──────────────────┴─────────────────────────────────┘
```

**Données Django (fenêtre glissante 12 mois) :**
```python
# Ces stats sont FIXES (ne changent pas au clic barre — calculées sur 12 mois rolling)
twelve_months_qs = Transaction.objects.filter(
    category=category,
    date__gte=today - relativedelta(months=12),
    is_ignored=False,
)
# avg par mois, % mois dépassant l'objectif, % transactions récurrentes
```

**Important :** Le bloc "En [mois X]" change à chaque clic barre (HTMX partial).
Le bloc "12 derniers mois" est FIXE — calculé une seule fois au chargement.

---

## RIGHT PANEL — Filtre "Comptes" + "Catégorie"
*Screenshot : `budget_spec/right_panel/budget_rightpanel_filtres_deplis.png`*

La rangée de filtres complète du right panel "Tout voir" :

```
[Tous les montants ▾]  [Tous les comptes ▾]  [1 catégorie ▾]   [Masquer les filtres]
```

**3 filtres + 1 toggle :**

| Filtre | Options | Session key |
|--------|---------|-------------|
| Tous les montants | Tout / Revenus / Dépenses + range ≤/≥/= | `panel_filter_amount` |
| Tous les comptes | Liste comptes actifs de l'user | `panel_filter_account` |
| [N] catégorie(s) | Multi-select catégories (pré-filtrée si ouvert depuis catégorie) | `panel_filter_category` |
| Masquer les filtres | Toggle affichage de la rangée | état JS local |

**Pré-filtrage "1 catégorie" :**
- Quand le panel est ouvert depuis une catégorie ("Tout voir" sur catégorie X), le filtre catégorie est pré-sélectionné sur X.
- L'URL du partial porte l'info : `GET /budget/panel/transactions/?category_id=X`
- → La vue Django pre-popule `panel_filter_category=X` dans la session.

**"Masquer les filtres" / "Afficher les filtres" :**
- Toggle JS local (pas serveur) — la rangée est visible ou cachée
- Quand cachée, le bouton affiche le nb de filtres actifs : "Afficher les filtres (2)"

---

## VALIDATION PLAN — Résultat du scan 2026-04-06

Après lecture de tous les 22 screenshots `budget_*` :

### ✅ Plan confirmé sans modification
- Sankey Chart.js (Phase 2A)
- KPIs row Entrées | Sorties | Disponible | Économisé — clic KPI filtre liste
- Distribution donut fixe droite
- Filtres catégories dropdown (✓ = sélectionné, pas ✓ = désélectionné)
- Toggle Sous-catégories dans filtre (vue filtrée 1 catégorie + sous-cats dans Sankey)
- Page catégorie : tabs Transactions | Sous-catégories | Objectif (tabs = KPI selectors)
- Topbar catégorie : `← [●] Nom [▾]` + filtres période/compte
- Historique bar chart 12 mois + clic barre → stats mises à jour
- Objectif gauge demi-cercle
- Right panel filtre montants (2 sections type + range) ✅
- Right panel filtre statut (Toutes / Pointées / Non pointées) ✅

### 🆕 Nouvelles specs ajoutées ce soir
1. **Détail transaction right panel** — structure complète avec is_ignored + is_reconciled toggles + "Modifier la transaction"
2. **Stats Historique** — 2 blocs ("En [mois]" + "12 derniers mois") avec 4 KPIs chacun
3. **Right panel filtre Comptes** — 3ème filtre manquant (après montants et catégorie)
4. **Pré-filtrage "1 catégorie"** — quand panel ouvert depuis catégorie X

### ⚠️ Rien de bloquant pour Phase 2A
Toutes les nouvelles specs sont pour Phase 2B+ (page catégorie, détail transaction). La Phase 2A (vue Budget principale) est correctement spécifiée.
