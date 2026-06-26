"""
tests/factories/categories.py — Factories pour les modèles OWNED de transactions/.

Category, SubCategory, CategorizationRule possèdent un champ `owner` nullable + un
manager fail-closed (#213) : `.objects.all()` → `.none()`. La lecture passe par
`.for_user(user)` (système OU perso de user) ou `.unscoped()`.

⚠️ Conséquence pour les factories : un objet PERSO n'est retrouvé via `.for_user(u)`
QUE si `owner == u`. On met donc `owner` EXPLICITEMENT (SubFactory User) par défaut →
les objets créés sont retrouvables par leur propriétaire. Pour un objet SYSTÈME
(partagé, owner NULL), utiliser la sous-factory dédiée `SystemCategoryFactory` ou
passer `owner=None, is_system=True`.

La création passe par `_create` (= Manager.create → ORM/_base interne), pas par
`objects.get_queryset()` fail-closed : créer fonctionne donc normalement.
"""

import factory

from transactions.models import CategorizationRule, Category, SubCategory

from .users import UserFactory


class CategoryFactory(factory.django.DjangoModelFactory):
    """
    Catégorie PERSO par défaut (owner = un user dédié, is_system=False).

    Reproduit la fixture `category`/`category_a` (colour_hex, order, is_system=False).
    django_get_or_create=("slug",) : slug unique → réutilisable sans IntegrityError.
    Pour une catégorie système partagée → SystemCategoryFactory.
    """

    class Meta:
        model = Category
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")
    colour_hex = "#aaaaaa"
    order = factory.Sequence(lambda n: n)
    is_system = False
    owner = factory.SubFactory(UserFactory)


class SystemCategoryFactory(CategoryFactory):
    """
    Catégorie SYSTÈME : owner NULL (partagée entre tous les users), is_system=True.
    Reproduit la fixture `system_category`. Visible par tout le monde via for_user().
    """

    is_system = True
    # SubFactory parente (owner=User) remise à NULL pour une catégorie système
    # partagée. mypy ne modélise pas les attributs déclaratifs factory_boy → ignore typé.
    owner = None  # type: ignore[assignment]


class SubCategoryFactory(factory.django.DjangoModelFactory):
    """
    Sous-catégorie PERSO. `owner` suit l'owner du parent (cohérence : une perso vit
    sous une catégorie de son propriétaire, ou sous une système). Reproduit `subcat`/`subcat_b`.
    """

    class Meta:
        model = SubCategory
        django_get_or_create = ("slug",)

    category = factory.SubFactory(CategoryFactory)
    name = factory.Sequence(lambda n: f"SubCategory {n}")
    slug = factory.Sequence(lambda n: f"subcategory-{n}")
    is_system = False
    owner = factory.SelfAttribute("category.owner")


class CategorizationRuleFactory(factory.django.DjangoModelFactory):
    """
    Règle de catégorisation PERSO (owner explicite, retrouvable via for_user).
    Reproduit `rule_a`/`rule_b` (target_field=display_name, is_active, priority).
    """

    class Meta:
        model = CategorizationRule

    keyword = factory.Sequence(lambda n: f"KEYWORD-{n}")
    category = factory.SubFactory(CategoryFactory)
    target_field = "display_name"
    priority = factory.Sequence(lambda n: n)
    is_active = True
    # owner dérivé de la catégorie (comme SubCategoryFactory) → rule.owner et
    # rule.category.owner restent cohérents par défaut (modèle owned #213), sauf
    # override explicite. Évite une règle perso pointant une catégorie d'un autre user.
    owner = factory.SelfAttribute("category.owner")
