---
paths:
  - "src/tests/**"
---

# Tests — conventions BricBudget (chargé sur les tests)

- pytest-django : `@pytest.mark.django_db` sur tout test qui touche la DB.
- Données de test : factories / fixtures (ex. helper `make_tx(...)` dans `tests/services/conftest.py`).
  **Pas** de dicts inline qui perdent le type `TransactionDict` — passer par le helper.
- Tester le **comportement**, pas l'implémentation.
- Vérifier **GET + POST** des vues touchées avant de déclarer terminé (test ou `manage.py shell`).
- `make test` (pytest) tourne en pre-push ; `make type` (mypy) + ruff + semgrep en CI.
