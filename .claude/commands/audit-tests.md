# /challenge-tests — Audit couverture + écriture tests manquants

> **Persona** : Tu es un testeur senior obsessionnel. Tu as vu des apps crasher en prod parce
> qu'une vue HTMX non testée retournait 500 sur un edge case. Tu ne fais pas confiance au fait
> qu'"on a vérifié dans le navigateur". Si ce n'est pas dans un test, ça n'existe pas.
>
> Référence qualité : Zulip backend tests + cookiecutter-django + Django docs testing tools.
> Chaque finding doit produire du code pytest prêt à coller dans un fichier de test.

---

## 0. Lire l'état des tests existants

```bash
# Structure des tests
find src/tests -name "*.py" | sort
# Nombre de tests par fichier
grep -rc "^def test_" src/tests/ | sort -t: -k2 -rn
# Tests qui passent
make test 2>&1 | tail -5
```

Lire en parallèle :
- `src/tests/conftest.py` — fixtures disponibles
- `src/tests/test_idor_protection.py` — IDOR existants
- `src/tests/test_internal_transfer.py` — toggle tests existants
- `src/budget/urls.py` — toutes les URLs déclarées
- `src/budget/views.py` — toutes les vues (signatures, decorators, logique POST/GET)

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
grep -n "@login_required" src/budget/views.py | wc -l
grep -c "requires_login" src/tests/test_idor_protection.py
```
Si le nombre de vues > nombre de tests login → écrire les manquants.

---

### Catégorie B — IDOR (Isolation données utilisateur)

Pour **chaque vue qui prend un `pk` ou `tx_id` en paramètre**, tester qu'un autre utilisateur reçoit 403 ou 404.

```python
# Pattern IDOR — à reproduire pour chaque vue avec pk
@pytest.mark.django_db
def test_idor_<vue>_blocked_for_other_user(client, django_user_model):
    user_a = django_user_model.objects.create_user("alice", password="pw")
    user_b = django_user_model.objects.create_user("bob", password="pw")
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
    other = django_user_model.objects.create_user("other", password="pw")
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
# Fonctions dans views.py non importées dans les tests
grep "^def _" src/budget/views.py
# Fonctions dans services.py
grep "^def " src/transactions/services.py
```

**Helpers prioritaires à tester :**

```python
# _vary_color — assombrit une couleur hex
def test_vary_color_full_factor_returns_original():
    from budget.views import _vary_color
    assert _vary_color("#4ade80", 1.0) == "#4ade80"

def test_vary_color_zero_factor_returns_black():
    from budget.views import _vary_color
    result = _vary_color("#4ade80", 0.0)
    assert result == "#000000"

def test_vary_color_invalid_hex_returns_fallback():
    from budget.views import _vary_color
    assert _vary_color("not-a-color", 0.5) == "#4ade80"

# _seg_factor — distribue n segments
def test_seg_factor_single_segment_returns_max():
    from budget.views import _seg_factor
    assert _seg_factor(0, 1) == 0.70

def test_seg_factor_first_segment_is_brightest():
    from budget.views import _seg_factor
    assert _seg_factor(0, 5) > _seg_factor(4, 5)

def test_seg_factor_last_segment_is_darkest():
    from budget.views import _seg_factor
    assert _seg_factor(4, 5) >= 0.35  # jamais en dessous du min lisible

# _compute_category_cashflow_context
def test_compute_category_cashflow_context_returns_expected_keys(rf, user, category):
    from budget.views import _compute_category_cashflow_context
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

def test_compute_category_cashflow_context_no_budget_target(rf, user, category):
    """Sans BudgetTarget → target_amount, target_pct, on_track, arc_fill_px = None."""
    from budget.views import _compute_category_cashflow_context
    request = rf.get("/")
    request.user = user
    request.session = {}
    ctx = _compute_category_cashflow_context(request, category)
    assert ctx["budget_target"] is None
    assert ctx["target_amount"] is None
    assert ctx["target_pct"] is None

def test_compute_category_cashflow_context_ignored_txs_excluded_from_total(
    rf, user, account, category
):
    """Les transactions is_ignored=True ne rentrent pas dans total_amount."""
    from budget.views import _compute_category_cashflow_context
    from decimal import Decimal
    Transaction.objects.create(account=account, category=category,
        amount=Decimal("-100"), is_ignored=False, ...)
    Transaction.objects.create(account=account, category=category,
        amount=Decimal("-50"), is_ignored=True, ...)  # doit être exclu
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
2. Lire `src/budget/urls.py` + `src/budget/views.py` (signatures uniquement)
3. Produire le tableau des gaps (section 1 ci-dessus)
4. Présenter à Emmanuel : "Voici les X gaps identifiés, dans cet ordre de priorité"

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

**Règle d'écriture :**
- Un test = un comportement. Jamais deux assertions métier dans un test.
- Nom du test = phrase en anglais qui décrit le comportement attendu.
  - ✅ `test_toggle_ignore_sets_is_ignored_to_true`
  - ❌ `test_toggle_ignore`
- Fixtures dans `conftest.py` si réutilisées dans 2+ fichiers, sinon locales.
- Toujours vérifier l'état DB après un POST (`.refresh_from_db()`).
- Toujours tester le cas "autre utilisateur" pour les vues avec pk.

### Phase 3 — Validation

```bash
make test
# Doit rester vert avec le nouveau score (ex: 245 passed / 0 failed)
make check
# 0 erreurs ruff + djlint
```

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

Si tu trouves ces patterns dans les tests existants, les noter comme dette :

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
- `make test` doit rester vert à chaque ajout de fichier
- Jamais de `--no-verify` ni de `pytest -k` pour skipper des tests gênants
- Les tests de query count sont des maximums, pas des cibles exactes (éviter la fragilité)
