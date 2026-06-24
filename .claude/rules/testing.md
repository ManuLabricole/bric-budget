---
paths:
  - "src/tests/**"
---

# Tests — conventions BricBudget (chargé sur les tests)

> Auditées par l'agent `test-auditor` et la commande `/challenge-tests`. Un test qui ne
> respecte pas ces règles ne PROUVE rien : il fait du théâtre (passe sans rien garantir).

## Obligatoire

- **Marker DB** : `@pytest.mark.django_db` sur tout test qui touche la base (style décorateur
  par test, comme `src/tests/budget/test_views.py`). Tout marker custom (`@pytest.mark.slow`…)
  DOIT être déclaré dans `pyproject.toml [tool.pytest.ini_options] markers` — sinon `--strict-markers`
  le rejette.
- **Factories, pas de `create()` inline répété.** Construire les objets via les factories de
  `src/tests/factories/` (livrées par #194 : `UserFactory`, `AccountFactory`, `TransactionFactory`,
  `CategoryFactory`…), PAS via des `Model.objects.create(...)` dupliqués champ par champ. La factory
  porte les champs obligatoires et n'expose que ce que le test fait varier → un ajout de champ NOT NULL
  ne casse pas 40 tests, et l'intention du test n'est plus noyée sous le setup.
  Helper legacy toléré tant qu'il existe (`make_tx(...)` dans `src/tests/services/conftest.py`) — mais
  pour un test de modèle/vue, viser la factory.
- **Tout test de VUE vérifie le RENDU**, pas juste le statut : `assertContains` (contenu attendu) +
  `assertTemplateUsed` (le bon template/partial). `assert response.status_code == 200` SEUL = théâtre :
  une vue peut renvoyer 200 avec une page vide ou le mauvais fragment. Pour un partial HTMX, asserter
  le contenu du fragment ET `assertNotContains(response, "<!DOCTYPE html>")` (inner HTML, pas page pleine).
- **Tout POST vérifie l'effet DB** : `obj.refresh_from_db()` puis `assert` sur le champ modifié.
  Un POST dont on ne vérifie que le statut ne teste pas la mutation.
- **Comportement, pas implémentation.** Tester via le client HTTP / l'API publique, pas en mockant
  un manager ou un queryset interne. Mocker UNIQUEMENT au boundary externe (réseau logos `_download`,
  `get_exchange_rate`, l'API Claude) — jamais la logique qu'on prétend valider.

## Structure & déterminisme

- **AAA** (Arrange-Act-Assert) : setup des données → une seule action → assertions. Un test =
  **un** comportement ; nom = phrase descriptive (`test_toggle_ignore_sets_is_ignored_to_true`,
  pas `test_toggle`). Pas deux assertions métier non liées dans le même test.
- **Déterminisme** : jamais `datetime.now()` / `date.today()` / `random` nu dans un test (casse
  selon le jour ou l'ordre). Dates FIXES (`date(2026, 3, 17)`), `random` seedé. Un cache/état global
  process-wide (`lru_cache`) se vide via un fixture `autouse` (cf. `_reset_icon_map_cache`, conftest racine).
- **IDOR** : toute vue prenant un `pk`/`slug` a un test « autre utilisateur → 403/404 » qui vérifie
  AUSSI que l'objet n'a pas changé (cf. `src/tests/budget/test_idor.py`, `src/tests/imports/test_idor.py`).
- **GET + POST** des vues touchées vérifiés avant de déclarer terminé (test ou `manage.py shell`).

## Exécution

- `make test` (pytest) tourne en pre-push ; `make type` (mypy) + ruff + semgrep en CI.
- Tests de query-count = des **maximums** (`django_assert_max_num_queries`), pas des cibles exactes
  (sinon fragiles). Ne jamais `--no-verify` ni `pytest -k` pour esquiver un test gênant.
