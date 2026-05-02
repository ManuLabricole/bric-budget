# Root conftest.py
#
# pytest-django lit DJANGO_SETTINGS_MODULE depuis pyproject.toml [tool.pytest.ini_options].
# Ce fichier est chargé en premier par pytest — il sert à déclarer des fixtures
# partagées entre tous les modules de tests si besoin à l'avenir.
#
# Pour l'instant : vide. Les fixtures spécifiques vivent dans les conftest.py
# de chaque sous-répertoire (src/tests/connectors/, src/tests/services/).
