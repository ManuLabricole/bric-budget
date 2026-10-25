"""
tests/e2e/test_category_create_subcategory.py — E2E création de sous-catégorie.

Régression : le picker de catégorie parente (panel "Nouvelle catégorie" → type
"Sous-catégorie") ne réagissait à AUCUN clic, sans erreur console. Cause :
`_panel_category_create.html` déléguait le clic sur `document.body`, or
`#modal-content` (base_app.html) porte `onclick="event.stopPropagation()"`
pour empêcher un clic DANS la modale de la fermer via le handler du fond
`#modal` — ce stopPropagation empêche aussi le clic d'atteindre `body`, donc
le listener délégué ne se déclenchait jamais. Fix : déléguer sur
`#modal-content` lui-même (le clic l'atteint AVANT que son propre onclick
n'arrête la propagation plus haut). Même correctif appliqué à
`_panel_rule_create_standalone.html` (picker catégorie de règle — même bug,
même cause, découvert en creusant ce ticket).

Ce test couvre le parcours réel : ouvrir le panel, basculer sur "Sous-catégorie",
cliquer une catégorie parente dans le picker, vérifier que la sélection
s'applique (valeur cachée + libellé), remplir nom + icône, et soumettre.
"""

import pytest

from tests.e2e.conftest import login


@pytest.fixture
def parent_category(transactional_db, e2e_user):
    """Catégorie perso pouvant servir de parent — DB e2e vierge de référentiel."""
    from transactions.models import Category

    return Category.objects.create(
        name="Alimentation E2E",
        slug="alimentation-e2e",
        owner=e2e_user,
        is_system=False,
        colour_hex="#e88c45",
        icon="tools-kitchen",
        order=10,
    )


@pytest.mark.e2e
def test_clicking_parent_category_selects_it(
    page, live_server, e2e_user, parent_category
):
    """Cliquer une catégorie dans le picker parent doit la sélectionner (pas de no-op)."""
    login(page, live_server)
    page.goto(f"{live_server.url}/budget/")

    page.click("text=Créer")
    page.click("text=Nouvelle catégorie")
    page.wait_for_selector("#cat-create-form")

    page.click("#btn-type-sub")
    page.wait_for_selector("#parent-picker-zone:not(.hidden)")

    page.click("#parent-picker-details summary")
    page.wait_for_selector(".js-cat-select[data-cat-target='cat-create-parent']")
    page.click(
        f".js-cat-select[data-cat-target='cat-create-parent'][data-cat-id='{parent_category.id}']"
    )

    # La sélection s'applique : hidden input renseigné, libellé mis à jour,
    # le <details> se referme (removeAttribute('open') dans applyParentSelection).
    assert page.locator("#parent-id-input").input_value() == str(parent_category.id)
    assert page.locator("#parent-label-preview").inner_text() == parent_category.name
    assert page.locator("#parent-picker-details").get_attribute("open") is None


@pytest.mark.e2e
def test_full_subcategory_creation_submits_successfully(
    page, live_server, e2e_user, parent_category
):
    """Parcours complet : parent + icône + nom → soumission → sous-catégorie créée."""
    login(page, live_server)
    page.goto(f"{live_server.url}/budget/")

    page.click("text=Créer")
    page.click("text=Nouvelle catégorie")
    page.wait_for_selector("#cat-create-form")

    page.click("#btn-type-sub")
    page.click("#parent-picker-details summary")
    page.click(
        f".js-cat-select[data-cat-target='cat-create-parent'][data-cat-id='{parent_category.id}']"
    )
    page.click(".icon-btn[data-icon='coffee']")
    page.fill("#cat-name-input", "Cafés E2E")

    assert page.locator("#cat-submit-btn").is_enabled()
    page.click("#cat-submit-btn")

    page.wait_for_selector("text=créée")

    from transactions.models import SubCategory

    # .objects est fail-closed (#213, manager perso) — .unscoped() pour lire
    # en tant que test, comme on créerait via l'ORM direct.
    sub = SubCategory.objects.unscoped().get(name="Cafés E2E")
    assert sub.category_id == parent_category.id
    assert sub.icon == "coffee"
