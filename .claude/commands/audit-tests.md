# /challenge-tests — Audit couverture + écriture tests manquants

> **Persona** : Tu es un testeur senior obsessionnel. Tu as vu des apps crasher en prod parce
> qu'une vue HTMX non testée retournait 500 sur un edge case. Tu ne fais pas confiance au fait
> qu'"on a vérifié dans le navigateur". Si ce n'est pas dans un test, ça n'existe pas.
>
> Référence qualité : Zulip backend tests + cookiecutter-django + Django docs testing tools.
> Chaque finding doit produire du code pytest prêt à coller dans un fichier de test.

> **Deux outils complémentaires — ne pas confondre :**
> - Cette commande `/challenge-tests` = **couverture** (quels comportements ne sont PAS testés)
>   → tu écris les tests manquants.
> - L'agent **`test-auditor`** (`.claude/agents/test-auditor.md`) = **qualité** des tests existants
>   (théâtre status-200, sur-mock, flaky, factories absentes, score de mutation) → il rapporte, ne code pas.
>
> Lance `test-auditor` AVANT cette commande : inutile d'écrire de nouveaux tests si ceux qui existent
> font déjà du théâtre. Toute la couverture que tu ajoutes DOIT respecter `.claude/rules/testing.md`
> (factories `src/tests/factories/`, `assertContains` + `assertTemplateUsed` sur les vues, vérif DB
> après POST, AAA, marker `@pytest.mark.django_db`).

---

## 0. Lire l'état des tests existants

```bash
# Structure des tests (package par app : tests/budget/, tests/imports/, tests/patrimoine/…)
find src/tests -name "test_*.py" | sort
# Nombre de tests par fichier
grep -rc "^def test_\|^    def test_" src/tests/ | sort -t: -k2 -rn
```
> ⛔ NE PAS lancer `make test` / `make check` à la main pour juger l'état de la suite —
> pre-push (pytest) + CI couvrent ça (cf. CLAUDE.md, cohérent avec la Phase 3 ci-dessous).
> Pour l'état réel : lire le dernier run CI (`gh run list`) ou le rapport de couverture.

Lire en parallèle (chemins RÉELS — la suite est structurée en packages par app) :
- `src/tests/conftest.py` + le `conftest.py` du sous-dossier visé (`src/tests/budget/conftest.py`,
  `src/tests/patrimoine/conftest.py`, `src/tests/connectors/conftest.py`, `src/tests/services/conftest.py`)
  — fixtures disponibles.
- `src/tests/factories/` — factories partagées (#194) à réutiliser pour tout nouvel objet de test.
- `src/tests/budget/test_idor.py` + `src/tests/imports/test_idor.py` — patterns IDOR existants.
- `src/tests/budget/test_views.py` — toggles, mouvements internes, états (`is_ignored`, `is_reconciled`).
- `src/budget/urls.py` (+ `imports/`, `patrimoine/`, `transactions/`, `users/urls.py`) — URLs déclarées.
- `src/budget/views/` — **package** de vues : `core.py`, `categories.py`, `transactions.py`, `rules.py`
  (signatures, decorators, logique POST/GET). ⛔ Il n'y a PLUS de `src/budget/views.py` à plat.

---

## 1. Cartographier les URLs vs tests existants

Pour chaque URL dans `budget/urls.py` (et les autres apps), produire un tableau :

| URL name | Vue | GET testé | POST testé | Auth testé | IDOR testé | HTMX testé |
|----------|-----|-----------|-----------|------------|------------|------------|
| budget:index | budget_index | ✅/❌ | — | ✅/❌ | — | ✅/❌ |
| budget:toggle_ignore | budget_toggle_ignore | — | ✅/❌ | ✅/❌ | ✅/❌ | ✅/❌ |
| ... | ... | ... | ... | ... | ... | ... |

**Règle** : une URL sans test GET + auth = gap critique.

---

## 2. Les 7 catégories de tests à challenger

### Catégorie A — Authentication (LOGIN REQUIRED)

Pour **chaque vue** protégée par `@login_required` :

```python
# Pattern à reproduire pour chaque URL protégée
@pytest.mark.django_db
def test_<vue>_requires_login(client):
    response = client.get(reverse("budget:<name>"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]
```

**Chercher les vues sans ce test :**
```bash
grep -rn "@login_required" src/budget/views/ | wc -l        # views/ = package, pas un .py à plat
grep -rc "requires_login" src/tests/budget/ | grep -v ':0'  # tests login existants (test_idor.py, test_views.py)
```
Si le nombre de vues > nombre de tests login → écrire les manquants.

---

### Catégorie B — IDOR (Isolation données utilisateur)

Pour **chaque vue qui prend un `pk` ou `tx_id` en paramètre**, tester qu'un autre utilisateur reçoit 403 ou 404.

```python
# Pattern IDOR — à reproduire pour chaque vue avec pk
@pytest.mark.django_db
def test_idor_<vue>_blocked_for_other_user(client, django_user_model):
    user_a = django_user_model.objects.create_user("alice", password="!")
    user_b = django_user_model.objects.create_user("bob", password="!")
    # Créer l'objet appartenant à user_b
    account_b = Account.objects.create(name="Compte B", ...)
    account_b.members.add(user_b)
    tx = Transaction.objects.create(account=account_b, ...)

    client.force_login(user_a)
    response = client.post(reverse("budget:toggle_ignore", args=[tx.id]), ...)
    assert response.status_code in (403, 404)
    # Vérifier que l'objet n'a PAS changé
    tx.refresh_from_db()
    assert tx.is_ignored == False  # inchangé
```

**Vues à vérifier impérativement :**
- `toggle_ignore` ✅ (déjà testé) → vérifier que le test inclut la vérification DB
- `toggle_reconcile` ✅ → idem
- `panel_tx_detail` ✅ → idem
- `budget_categorize_transaction` ✅ → idem
- `budget_toggle_filter_account` — testé ?
- `budget_category_cashflow_fragment` — NOUVEAU → testé ?
- `budget_category_detail` — GET avec slug → testé ?
- `budget_modal_budget_target_*` — testé ?
- Toutes les vues `rules_*` qui prennent un pk

---

### Catégorie C — HTTP Method enforcement

Les vues POST-only doivent retourner 405 sur un GET :

```python
@pytest.mark.parametrize("url_name,kwargs", [
    ("budget:toggle_ignore", {"tx_id": 1}),
    ("budget:toggle_reconcile", {"tx_id": 1}),
    ("budget:categorize", {"tx_id": 1}),
    # etc.
])
def test_post_only_views_reject_get(client, user, url_name, kwargs):
    client.force_login(user)
    response = client.get(reverse(url_name, kwargs=kwargs))
    assert response.status_code == 405
```

---

### Catégorie D — Réponses HTMX

Pour **chaque vue qui retourne un partial HTMX**, tester :

#### D1 — Headers HTMX spéciaux (HX-Redirect, HX-Refresh)
```python
def test_<vue>_htmx_returns_hx_redirect(client, user, tx):
    client.force_login(user)
    response = client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "detail", "close_on_back": "false"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    # Vérifier qu'il N'y a PAS de HX-Redirect (panneau reste ouvert)
    assert not response.has_header("HX-Redirect")
```

#### D2 — OOB swaps (hx-swap-oob)
```python
def test_toggle_ignore_close_on_back_returns_oob_row(client, user, tx):
    client.force_login(user)
    response = client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "detail", "close_on_back": "true"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL=f"/budget/categorie/{tx.category.slug}/",
    )
    content = response.content.decode()
    assert 'hx-swap-oob="outerHTML"' in content  # OOB row présent
    assert "data-cashflow-refresh" in content      # signal JS présent
    assert not response.has_header("HX-Redirect") # plus de reload complet
```

#### D3 — Fragment cashflow (nouveau endpoint)
```python
def test_category_cashflow_fragment_returns_200(client, user, category):
    client.force_login(user)
    response = client.get(reverse("budget:category_cashflow_fragment", args=[category.slug]))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Cashflow" in content
    assert "<!DOCTYPE html>" not in content  # pas de page complète
    assert "<html" not in content            # inner HTML only

def test_category_cashflow_fragment_requires_login(client, category):
    response = client.get(reverse("budget:category_cashflow_fragment", args=[category.slug]))
    assert response.status_code == 302

def test_category_cashflow_fragment_idor_blocked(client, django_user_model, category):
    other = django_user_model.objects.create_user("other", password="!")
    client.force_login(other)
    # si la catégorie n'appartient pas à l'user → 404
    response = client.get(reverse("budget:category_cashflow_fragment", args=[category.slug]))
    # vérifier qu'on ne voit pas les données d'un autre user
    assert response.status_code in (200, 404)  # 200 OK mais données vides
```

#### D4 — Toggle state cohérence (DB + rendu)
```python
def test_toggle_ignore_flips_state_and_renders_correct_css(client, user, tx):
    """Le toggle doit changer le state ET le rendu CSS reflète le nouvel état."""
    assert not tx.is_ignored  # état initial
    client.force_login(user)
    response = client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "list"},
    )
    # DB changée
    tx.refresh_from_db()
    assert tx.is_ignored is True
    # Rendu : opacity-40 présent pour transaction ignorée
    assert "opacity-40" in response.content.decode()

def test_toggle_ignore_double_flip_restores_state(client, user, tx):
    """Toggler deux fois = état initial."""
    client.force_login(user)
    for _ in range(2):
        client.post(reverse("budget:toggle_ignore", args=[tx.id]), {"source": "list"})
    tx.refresh_from_db()
    assert tx.is_ignored is False
```

---

### Catégorie E — Logique métier (helpers + services)

Chaque helper ou fonction pure doit avoir un test unitaire. Chercher les fonctions non testées :

```bash
# Fonctions privées dans le package de vues (views/ n'est PAS un .py à plat)
grep -rn "^def _" src/budget/views/
# Helpers purs hors vues (couleurs, périodes, etc.)
grep -n "^def _" src/budget/utils.py
# Fonctions de service (services/ = package : file_hash.py, import_service.py, internal_transfer.py)
grep -rn "^def " src/transactions/services/
```

> ⚠️ Les helpers de cet exemple existent ET sont déjà testés (`_vary_color`/`_seg_factor` dans
> `src/budget/utils.py` → `src/tests/budget/test_utils.py` ; `_compute_category_cashflow_context`
> dans `src/budget/views/categories.py` → `src/tests/budget/test_helpers.py`). Patterns donnés à
> titre illustratif — **vérifie d'abord** ce qui manque réellement avec les greps ci-dessus.
> Les imports pointent vers le module réel (chemins corrigés).

**Patterns de test de helper pur (imports réels) :**

```python
# _vary_color / _seg_factor vivent dans budget.utils (PAS budget.views)
def test_vary_color_full_factor_returns_original():
    from budget.utils import _vary_color
    assert _vary_color("#4ade80", 1.0) == "#4ade80"

def test_vary_color_invalid_hex_returns_fallback():
    from budget.utils import _vary_color
    assert _vary_color("not-a-color", 0.5) == "#4ade80"

def test_seg_factor_first_segment_is_brightest():
    from budget.utils import _seg_factor
    assert _seg_factor(0, 5) > _seg_factor(4, 5)

# _compute_category_cashflow_context vit dans budget.views.categories
def test_compute_category_cashflow_context_returns_expected_keys(rf, user, category):
    from budget.views.categories import _compute_category_cashflow_context
    request = rf.get("/")
    request.user = user
    request.session = {}
    ctx = _compute_category_cashflow_context(request, category)
    required_keys = [
        "period_start", "period_end", "period_mode", "period_label",
        "period_months", "filter_account_ids", "base_qs", "txs_active",
        "total_amount", "subcat_list", "subcat_colors", "cat_color",
        "sankey_data", "has_sankey", "tx_count", "cat_tab",
        "subcat_count", "budget_target", "target_amount",
        "target_pct", "on_track", "arc_fill_px",
    ]
    for key in required_keys:
        assert key in ctx, f"Missing key: {key}"

def test_compute_category_cashflow_context_ignored_txs_excluded_from_total(
    rf, user, account, category
):
    """Les transactions is_ignored=True ne rentrent pas dans total_amount."""
    from budget.views.categories import _compute_category_cashflow_context
    from decimal import Decimal
    # Via factory (rules/testing.md) plutôt que objects.create inline :
    TransactionFactory(account=account, category=category,
        amount=Decimal("-100"), is_ignored=False)
    TransactionFactory(account=account, category=category,
        amount=Decimal("-50"), is_ignored=True)  # doit être exclu
    request = rf.get("/")
    request.user = user
    request.session = {}
    ctx = _compute_category_cashflow_context(request, category)
    assert abs(ctx["total_amount"]) == Decimal("100")  # 50 ignoré
```

---

### Catégorie F — Rendu templates (assertContains + assertInHTML)

Pour les vues qui rendent des templates complexes :

```python
def test_budget_index_shows_category_list(client, user, account, category):
    """La page index liste les catégories actives."""
    client.force_login(user)
    response = client.get(reverse("budget:index"))
    assert response.status_code == 200
    assertContains(response, category.name)
    assertTemplateUsed(response, "budget/index.html")

def test_category_detail_shows_sankey_when_transactions_exist(client, user, account, category):
    """Sankey présent si transactions actives sur la période."""
    client.force_login(user)
    # créer une transaction sur la période courante
    Transaction.objects.create(
        account=account, category=category,
        amount=Decimal("-50"), date=date.today(), is_ignored=False, ...
    )
    response = client.get(reverse("budget:category_detail", args=[category.slug]))
    assert response.status_code == 200
    assertContains(response, 'id="sankey-chart"')
    assertContains(response, 'id="sankey-data"')

def test_category_detail_no_sankey_when_no_transactions(client, user, category):
    """Pas de Sankey si aucune transaction sur la période."""
    client.force_login(user)
    response = client.get(reverse("budget:category_detail", args=[category.slug]))
    assertNotContains(response, 'id="sankey-chart"')

def test_panel_tx_detail_shows_internal_transfer_badge(client, user, account):
    """Badge mouvement interne affiché si is_internal_transfer=True."""
    client.force_login(user)
    tx = Transaction.objects.create(
        account=account, is_internal_transfer=True, is_ignored=True, ...
    )
    response = client.get(reverse("budget:panel_tx_detail", args=[tx.id]))
    assertContains(response, "mouvement interne")

def test_panel_tx_detail_no_badge_for_normal_tx(client, user, account):
    """Pas de badge pour une transaction normale."""
    client.force_login(user)
    tx = Transaction.objects.create(account=account, is_internal_transfer=False, ...)
    response = client.get(reverse("budget:panel_tx_detail", args=[tx.id]))
    assertNotContains(response, "mouvement interne")
```

---

### Catégorie G — Query count (anti N+1)

Chaque vue qui charge des listes DOIT être testée avec un dataset réaliste :

```python
@pytest.mark.django_db
def test_budget_index_query_count_does_not_grow_with_transactions(
    client, user, account, django_assert_max_num_queries
):
    """Pas de N+1 : 50 transactions = même nb de queries que 5."""
    from transactions.models import Transaction
    client.force_login(user)

    # 5 transactions
    Transaction.objects.bulk_create([
        Transaction(account=account, amount=Decimal(f"-{i}"), ...) for i in range(5)
    ])
    with django_assert_max_num_queries(15) as q5:
        client.get(reverse("budget:index"))

    # 50 transactions
    Transaction.objects.bulk_create([
        Transaction(account=account, amount=Decimal(f"-{i}"), ...) for i in range(45)
    ])
    with django_assert_max_num_queries(15) as q50:
        client.get(reverse("budget:index"))
    # Le nombre de queries NE DOIT PAS augmenter proportionnellement
    # (si q50 >> q5, il y a un N+1)

@pytest.mark.django_db
def test_category_detail_query_count(client, user, account, category,
                                      django_assert_max_num_queries):
    Transaction.objects.bulk_create([
        Transaction(account=account, category=category,
                    amount=Decimal("-10"), ...) for _ in range(20)
    ])
    client.force_login(user)
    with django_assert_max_num_queries(20):
        client.get(reverse("budget:category_detail", args=[category.slug]))
```

---

## 3. Workflow d'exécution

### Phase 1 — Audit (ne pas coder encore)

1. Lire tous les fichiers de tests existants
2. Lire `src/budget/urls.py` + le package `src/budget/views/` (`core.py`, `categories.py`,
   `transactions.py`, `rules.py` — signatures uniquement)
3. (Recommandé) Lancer l'agent `test-auditor` sur le module visé → trier d'abord la dette de
   QUALITÉ avant d'ajouter de la couverture.
4. Produire le tableau des gaps (section 1 ci-dessus)
5. Présenter à Emmanuel : "Voici les X gaps identifiés, dans cet ordre de priorité"

### Phase 2 — Écriture des tests (après validation)

Pour chaque gap, dans cet ordre de priorité :

```
1. Auth manquant       → toujours le plus critique
2. IDOR manquant       → sécurité données
3. Nouveau endpoint    → budget_category_cashflow_fragment
4. HTMX response       → headers, OOB, state flip
5. Helpers/services    → logique pure
6. Rendu templates     → assertContains
7. Query count         → performance
```

**Règle d'écriture** (étalon complet : `.claude/rules/testing.md`) :
- Un test = un comportement. Jamais deux assertions métier dans un test. AAA (Arrange-Act-Assert).
- Nom du test = phrase en anglais qui décrit le comportement attendu.
  - ✅ `test_toggle_ignore_sets_is_ignored_to_true`
  - ❌ `test_toggle_ignore`
- **Factories** (`src/tests/factories/`, #194) pour créer les objets, pas de `objects.create()` inline répété.
- **Tout test de vue** : `assertContains` + `assertTemplateUsed` — jamais `status_code == 200` seul.
- Fixtures dans le `conftest.py` du sous-dossier si réutilisées dans 2+ fichiers, sinon locales.
- Toujours vérifier l'état DB après un POST (`.refresh_from_db()`).
- Toujours tester le cas "autre utilisateur" pour les vues avec pk/slug (IDOR).
- `@pytest.mark.django_db` sur tout test qui touche la DB.

### Phase 3 — Validation

- ⛔ NE PAS lancer `make check` / `make test` à la main : pre-commit (ruff/djlint) + pre-push (pytest) +
  CI (mypy/semgrep) couvrent tout (cf. CLAUDE.md). On commit/push et on laisse les hooks tourner.
- La **vérif live GET + POST** (via `manage.py shell` ou l'app réelle) reste DUE — elle n'est PAS
  couverte par la CI.
- Repasser l'agent `test-auditor` sur les fichiers ajoutés : zéro nouveau finding 🔴 (pas de théâtre
  réintroduit) avant de proposer la PR.

---

## 4. Fixtures recommandées à ajouter dans conftest.py

Si absentes, les ajouter :

```python
@pytest.fixture
def htmx_client(client):
    """Client HTMX — envoie HTTP_HX_REQUEST='true' sur chaque requête."""
    client.defaults["HTTP_HX_REQUEST"] = "true"
    return client

@pytest.fixture
def other_user(db, django_user_model):
    """Second utilisateur pour les tests IDOR."""
    return django_user_model.objects.create_user(
        username="other_user_idor",
        password="testpass_idor_456",  # gitleaks:allow (fixture de test, pas un secret)
    )

@pytest.fixture
def tx_ignored(account, cat_alim):
    """Transaction is_ignored=True pour tester les états exclus."""
    return Transaction.objects.create(
        account=account, category=cat_alim,
        amount=Decimal("-25.00"), is_ignored=True,
        date=date.today(), description_raw="Test ignored",
        import_hash="ignored_hash_001",
    )
```

---

## 5. Anti-patterns à rejeter

Si tu trouves ces patterns dans les tests existants, les noter comme dette. **L'agent
`test-auditor` automatise cette détection** (théâtre status-200, sur-mock, flaky, factories
absentes, score de mutation) — lance-le pour une matrice complète plutôt que de greper à la main.

| Anti-pattern | Problème | Fix |
|-------------|----------|-----|
| `assert response.status_code == 200` sans assertContains | Coverage theater | Ajouter assertions contenu |
| Test qui ne vérifie pas l'état DB après POST | Ne teste pas la vraie logique | Ajouter `.refresh_from_db()` |
| Fixture qui crée 0 transactions pour un test de liste | Faux positif | Créer au moins 1 objet réaliste |
| Test nommé `test_view_works` | Incompréhensible | Renommer en comportement |
| Test qui importe directement depuis la vue | Couplage à l'implémentation | Tester via HTTP |

---

## 6. Output attendu

```
## Audit couverture — YYYY-MM-DD

### 📊 Score actuel
- X tests existants
- Y URLs déclarées
- Z URLs sans aucun test

### 🔴 Gaps critiques (à traiter avant merge)
1. ...
2. ...

### 🟡 Gaps importants (à traiter en Phase 3)
1. ...

### 🟢 Couverture satisfaisante
- IDOR : X/Y vues couvertes
- Auth : X/Y vues couvertes

### 📝 Tests écrits cette session
- test_xxx.py : N nouveaux tests
- Score final : N passed / 0 failed
```

---

## Règles

- Ne jamais modifier un test existant qui passe sans raison explicite
- Ne jamais supprimer un test (même si il semble redondant — discuter d'abord)
- Si un test révèle un vrai bug → signaler immédiatement, ne pas contourner
- La suite doit rester verte (pre-push pytest) — ne PAS la lancer à la main avant commit (cf. CLAUDE.md)
- Jamais de `--no-verify` ni de `pytest -k` pour skipper des tests gênants
- Les tests de query count sont des maximums, pas des cibles exactes (éviter la fragilité)
