"""
tests/commands/test_command_smoke.py — filet sur TOUTES les commandes du projet (#126).

Charge chaque commande management des apps BricBudget : un import cassé ou un
argparse cassé devient un test rouge en CI — aucune commande ne peut arriver
inchargeable en prod. (Ne les EXÉCUTE pas : les comportements sont testés dans
leurs fichiers dédiés — ici on garantit juste qu'elles se chargent.)
"""

import pytest
from django.core.management import get_commands, load_command_class

PROJECT_APPS = {"accounts", "transactions", "patrimoine", "users"}


def _project_commands() -> list[str]:
    return sorted(
        name
        for name, app in get_commands().items()
        if app.split(".")[0] in PROJECT_APPS
    )


def test_project_has_commands():
    """Le filtre doit attraper nos commandes — un set vide serait un faux vert."""
    commands = _project_commands()
    assert "sync_reference_data" in commands
    assert "seed_institutions" in commands


@pytest.mark.parametrize("name", _project_commands())
def test_command_loads_and_renders_help(name):
    command = load_command_class(get_commands()[name], name)
    parser = command.create_parser("manage.py", name)
    assert parser.format_help()
