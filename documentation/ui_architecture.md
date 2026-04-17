# UI Architecture — BricBudget
> Décision finale : 2026-04-06
> Stack : Django 6 + HTMX 2 + Tailwind CSS 3

---

## Principes directeurs

| Principe | Décision | Pourquoi |
|----------|----------|----------|
| Zéro JS custom | HTMX pour toutes les interactions | Pas de framework JS — état géré côté serveur Django |
| État UI en session | `request.session` pour filtres, période, compte actif | Pas d'URL params (décision 2026-04-01) |
| Partial natif Django 6 | `render_to_string('template.html#block')` | Évite `django-htmx` comme dépendance supplémentaire |
| Includes > django-components | `{% include %}` pour composants statiques | django-components = 4x plus lent, overkill ici |
| Template tags pour logique | `@register.inclusion_tag` quand logique Python nécessaire | Montants colorés, badges catégorie — besoin de calcul |
| 2 niveaux héritage max | `base.html` → `base_app.html` → page | Au-delà les `{% block %}` deviennent intraçables |

---

## Layout global — 3 colonnes

```
┌──────────────────────────────────────────────────────────────────┐
│  SIDEBAR (240px fixe)  │  MAIN (flex-1, scroll)  │  RIGHT PANEL  │
│                        │                          │  (384px)      │
│  🏦 BricBudget         │  {% block topbar %}      │  slide-in     │
│                        │  ─────────────────────   │  hors écran   │
│  📋 Transactions       │                          │  par défaut   │
│  📊 Budget             │  {% block content %}     │               │
│  💰 Comptes            │                          │  HTMX target  │
│  ⚙️  Paramètres        │                          │  sur clic     │
│                        │                          │  ligne tx     │
│  ──────────────────    │                          │               │
│  Emmanuel Barriol      │                          │               │
└──────────────────────────────────────────────────────────────────┘
```

### Structure HTML du layout

```html
<!-- base_app.html — ne jamais modifier ce squelette -->
<div class="flex h-screen bg-[#111318] overflow-hidden">

  <!-- SIDEBAR — ne scroll pas, toujours visible -->
  <aside class="w-60 flex-shrink-0 flex flex-col border-r border-zinc-800">
    {% include "components/layout/sidebar.html" %}
  </aside>

  <!-- MAIN — scroll indépendant de la sidebar -->
  <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
    {% include "components/layout/topbar.html" %}
    <main class="flex-1 overflow-y-auto p-6">
      {% block content %}{% endblock %}
    </main>
  </div>

  <!-- RIGHT PANEL — fixed, hors flux, caché par défaut -->
  <!-- translate-x-full = décalé de 100% à droite = invisible -->
  <!-- JS minimal : openPanel() retire cette class, closePanel() la remet -->
  <aside id="right-panel"
         class="w-96 flex-shrink-0 flex flex-col border-l border-zinc-800
                transform translate-x-full transition-transform duration-300
                fixed right-0 top-0 h-full z-40 bg-[#1a1d24]">
    {% include "components/layout/right_panel.html" %}
  </aside>

</div>
```

**Pourquoi `fixed` sur le right panel ?**
`fixed` le sort du flux normal — il ne pousse pas le contenu principal. Sans `fixed`, ouvrir le panneau réduirait la zone `MAIN` et provoquerait un layout shift.

---

## Héritage des templates

```
base.html               ← shell HTML pur (head, Tailwind CDN, HTMX CDN, scripts globaux)
    │
    └── base_app.html   ← layout 3 colonnes (sidebar + main + right panel)
            │
            ├── transactions/list.html
            ├── budget/index.html
            └── accounts/index.html   (Phase 4+)
```

### Blocs définis dans `base.html`

| Bloc | Usage |
|------|-------|
| `{% block title %}` | Titre onglet navigateur |
| `{% block extra_head %}` | CSS ou meta spécifiques à une page |
| `{% block body %}` | Contenu `<body>` — surchargé par `base_app.html` |
| `{% block extra_js %}` | Scripts en fin de page (Chart.js sur budget uniquement) |

### Blocs définis dans `base_app.html`

| Bloc | Usage |
|------|-------|
| `{% block topbar %}` | Titre de page + boutons contextuels (ex: "Importer") |
| `{% block content %}` | Corps de page — surchargé par chaque page |
| `{% block panel %}` | Contenu initial du right panel (vide par défaut) |

---

## Structure complète des templates

```
src/templates/
│
├── base.html                            ← shell HTML pur
├── base_app.html                        ← layout 3 colonnes
│
├── components/                          ← UI statique — {% include %} avec with
│   │
│   ├── layout/
│   │   ├── sidebar.html                 ← navigation fixe gauche
│   │   ├── topbar.html                  ← barre titre + actions contextuelles
│   │   └── right_panel.html             ← shell panneau droit (vide au chargement)
│   │
│   ├── data/                            ← affichage de données métier
│   │   ├── amount.html                  ← montant coloré + devise (vert=crédit, rouge=débit)
│   │   ├── category_badge.html          ← emoji + nom + pastille couleur catégorie
│   │   ├── account_badge.html           ← logo banque + nom + devise
│   │   └── stat_chip.html               ← KPI chip : label + valeur + variation
│   │
│   ├── ui/                              ← primitives UI réutilisables
│   │   ├── card.html                    ← conteneur card (bg-zinc-900, rounded, padding)
│   │   ├── badge.html                   ← badge générique (couleur passée en param)
│   │   ├── button.html                  ← bouton (variant: primary / ghost / danger)
│   │   ├── empty_state.html             ← état vide (icône + message + CTA optionnel)
│   │   └── spinner.html                 ← loader HTMX (visible pendant hx-indicator)
│   │
│   └── forms/
│       ├── filter_bar.html              ← barre filtres (compte / période / catégorie)
│       ├── select.html                  ← <select> stylé Tailwind
│       └── date_range.html              ← date_from + date_to (2 inputs)
│
├── partials/                            ← fragments HTMX rechargés dynamiquement
│   │                                       convention : prefixe _ pour les partials
│   ├── transactions/
│   │   ├── _table.html                  ← tableau complet (rechargé sur filtre)
│   │   ├── _row.html                    ← une ligne (rechargée après inline edit)
│   │   └── _panel_detail.html           ← contenu panneau droit : détail + édition tx
│   │
│   ├── budget/
│   │   ├── _stats_row.html              ← KPIs : Revenus / Dépenses / Disponible
│   │   ├── _waterfall.html              ← graphique Chart.js (rechargé sur filtre)
│   │   └── _category_list.html          ← liste catégories + montants + barres
│   │
│   └── shared/
│       ├── _pagination.html             ← précédent / suivant / page X sur Y
│       └── _toast.html                  ← notification flash (déclenché par HX-Trigger)
│
├── transactions/
│   └── list.html                        ← page complète transactions (étend base_app.html)
│
├── budget/
│   └── index.html                       ← page complète budget (étend base_app.html)
│
├── accounts/
│   └── index.html                       ← page complète comptes — Phase 4
│
└── registration/
    └── login.html                       ← ✅ existant — ne pas modifier
```

---

## Template tags — `transactions/templatetags/budget_tags.py`

Logique Python qui ne peut pas vivre dans un `{% include %}` pur.

```python
from django import template
register = template.Library()

@register.inclusion_tag("components/data/amount.html")
def amount(value, currency):
    """
    Affiche un montant coloré.
    - Positif (crédit)  → text-emerald-400 avec préfixe "+"
    - Négatif (débit)   → text-red-400 avec préfixe "−"

    Usage dans un template : {% amount transaction.amount transaction.currency %}
    """
    return {
        "value": abs(value),
        "currency": currency,
        "is_positive": value >= 0,
        "color": "text-emerald-400" if value >= 0 else "text-red-400",
        "sign": "+" if value >= 0 else "−",
    }

@register.inclusion_tag("components/data/category_badge.html")
def category_badge(category, subcategory=None):
    """
    Badge catégorie : emoji + nom + couleur de fond.
    Si subcategory fournie, affiche le nom de la sous-cat.

    Usage : {% category_badge transaction.category transaction.subcategory %}
    """
    return {
        "emoji": category.icon if category else "❓",
        "name": subcategory.name if subcategory else (category.name if category else "Non catégorisé"),
        "color_hex": category.colour_hex if category else "#6b7280",
    }
```

---

## Pattern HTMX — filtre → rechargement table

```
1. Utilisateur modifie un filtre (compte, période, catégorie)

2. HTMX intercepte le changement :
   hx-get="/transactions/"
   hx-target="#tx-table"
   hx-trigger="change"
   hx-push-url="false"          ← état en session, pas dans l'URL

3. Vue Django :
   if request.headers.get("HX-Request"):
       # Persist filters in session
       request.session["tx_filter_account"] = request.GET.get("account")
       request.session["tx_filter_period"]  = request.GET.get("period")
       # Return partial only
       return render(request, "partials/transactions/_table.html", context)
   else:
       # Full page (first load, direct URL access)
       return render(request, "transactions/list.html", context)

4. HTMX remplace le contenu de #tx-table uniquement
   → Sidebar, topbar, filtres restent intacts
```

---

## Pattern HTMX — ouverture right panel

```
1. Utilisateur clique sur une ligne de transaction

2. HTMX sur le <tr> ou un bouton :
   hx-get="/transactions/{{ tx.id }}/panel/"
   hx-target="#panel-content"
   hx-on::after-request="openPanel()"

3. Vue Django :
   def transaction_panel(request, pk):
       tx = get_object_or_404(Transaction, pk=pk)
       # Toujours un partial — cette URL n'a pas de version full-page
       return render(request, "partials/transactions/_panel_detail.html", {"tx": tx})

4. HTMX injecte la réponse dans #panel-content
   openPanel() retire "translate-x-full" → panneau slide depuis la droite

5. Fermeture : bouton "✕" dans right_panel.html appelle closePanel()
```

### JS minimal dans `base_app.html` (les 2 seules fonctions JS du projet)

```html
<script>
  function openPanel() {
    document.getElementById('right-panel').classList.remove('translate-x-full');
  }
  function closePanel() {
    document.getElementById('right-panel').classList.add('translate-x-full');
  }
</script>
```

---

## Design system — palette inspirée Finary

| Token | Classe Tailwind | Valeur hex | Usage |
|-------|----------------|-----------|-------|
| `bg-app` | `bg-[#111318]` | `#111318` | Fond global de l'app |
| `bg-card` | `bg-zinc-900` | `#18181b` | Cartes, panneaux, tableau |
| `bg-card-hover` | `bg-zinc-800` | `#27272a` | Hover ligne transaction |
| `bg-panel` | `bg-[#1a1d24]` | `#1a1d24` | Right panel, sidebar |
| `text-primary` | `text-white` | `#ffffff` | Titres, montants principaux |
| `text-secondary` | `text-zinc-300` | `#d4d4d8` | Noms marchands, valeurs |
| `text-muted` | `text-zinc-400` | `#a1a1aa` | Labels, dates, meta |
| `text-disabled` | `text-zinc-600` | `#52525b` | Placeholders, inactifs |
| `accent-income` | `text-emerald-400` | `#34d399` | Montants positifs (crédits) |
| `accent-expense` | `text-red-400` | `#f87171` | Montants négatifs (débits) |
| `accent-gold` | `text-amber-400` | `#fbbf24` | Highlights nav, accents |
| `border` | `border-zinc-800` | `#27272a` | Séparateurs, contours card |
| `border-subtle` | `border-zinc-700` | `#3f3f46` | Bordures hover, focus |

---

## Règles à respecter

1. **Un partial = un `id` DOM.** Un fragment HTMX cible exactement un élément. Ne jamais retourner un partial qui met à jour plusieurs zones (utiliser `hx-swap-oob` en dernier recours seulement).

2. **Pas d'état dans l'URL.** Filtres et période en session Django. `hx-push-url="false"` sur tous les appels de filtres.

3. **Composants sans logique DB.** Les fichiers dans `components/` reçoivent leurs données via `{% include ... with var=val %}`. Ils n'interrogent jamais la DB.

4. **`{% load budget_tags %}` en haut de chaque template** qui utilise les template tags.

5. **Convention nommage partials.** Tous les fichiers dans `partials/` commencent par `_` pour les distinguer visuellement des pages complètes.

6. **right panel = contenu chargé lazy.** Le shell `right_panel.html` est rendu avec la page. Son contenu (`#panel-content`) est vide et chargé par HTMX au premier clic.

---

## Ordre de construction Phase 1B

L'ordre respecte les dépendances : pas de page sans layout, pas de table sans composants de base.

1. `base.html` + `base_app.html` — le shell, ne change plus après
2. `components/layout/sidebar.html` + `topbar.html` + `right_panel.html`
3. `components/data/amount.html` + `category_badge.html` (template tags)
4. `components/forms/filter_bar.html`
5. `partials/transactions/_table.html` + `_row.html`
6. `transactions/list.html` — page complète
7. `partials/shared/_pagination.html`
8. Vue Django `transactions_list` + `transaction_panel`

Items 9+ (Phase 1C) : `_panel_detail.html` + inline edit forms.
