"""
transactions/managers.py — Couche-2 ORM fail-closed pour les modèles « owned ».

Issue #213 (Part of #204, Phase 1.5). Source de vérité : OwnedManager / OwnedQuerySet.

CONTEXTE — pourquoi cette couche
================================
Avant #213, le scoping par owner était **opt-in / fail-OPEN** : chaque vue devait
penser à appeler `.for_user(user)`. Un seul `.objects.all()` nu oublié = fuite de
données d'un autre user (cf. leak #118, finding F1).

`OwnedManager` inverse la valeur par défaut → **fail-CLOSED** :

    Model.objects.all()            # → .none() (0 ligne, PAS la donnée d'autrui)
    Model.objects.for_user(user)   # → système (owner NULL) OU perso (owner=user)
    Model.objects.unscoped()       # → accès GLOBAL, SEUL point de bypass, grep-able

`grep -rn "unscoped(" src/` donne la liste exhaustive et auditable des accès
globaux légitimes (seeds, admin, commands, import_service).

GARDE-FOU INTERNES DJANGO
=========================
Un `get_queryset()` qui renvoie `.none()` par défaut casserait les internes Django
(reverse-FK / FK descriptors, related lookups) qui passent par le **base manager**.
On neutralise ça avec `Meta.base_manager_name = "_base_manager"` côté modèle :
Django utilise alors un manager plain (`get_queryset()` non borné) pour ses lookups
relationnels, tandis que `objects` (le default manager applicatif) reste fail-closed.

MÉCANIQUE
=========
`for_user` et `unscoped` NE partent PAS de `self.get_queryset()` (qui est `.none()`)
mais construisent un OwnedQuerySet **non borné** directement depuis le modèle. Sinon
elles hériteraient du `.none()` et ne retourneraient jamais rien.
"""

from django.db import models


class OwnedQuerySet(models.QuerySet):
    """
    QuerySet partagé par tout modèle possédant un champ `owner` nullable :
    Category, SubCategory, CategorizationRule, BudgetTarget (#137, #145, #213).

    Méthode principale : .for_user(user)
        Retourne les objets visibles par `user` :
            - objets système (owner IS NULL, partagés entre tous les users) ;
            - objets perso dont `user` est le propriétaire.

        Un objet perso d'un AUTRE user n'est JAMAIS retourné → garantit
        l'isolation multi-user au niveau du référentiel.

        Pourquoi sur le QuerySet et pas inline dans chaque vue ? DRY + sécurité :
        un seul point de vérité pour la règle « système OU à moi », chaînable.
    """

    def for_user(self, user):
        return self.filter(models.Q(owner__isnull=True) | models.Q(owner=user))


class OwnedManager(models.Manager):
    """
    Manager fail-closed pour les modèles owned (#213).

    `get_queryset()` renvoie `.none()` : tout accès NON scopé (`.objects.all()`,
    `.objects.filter(...)`, itération directe, related-manager applicatif) ne voit
    AUCUNE ligne par défaut. Le scope doit être EXPLICITE.

    Deux portes pour obtenir des lignes :
        - `for_user(user)`  → scope sécurité (système OU perso de `user`) ;
        - `unscoped()`      → accès GLOBAL, SEUL bypass légitime, grep-able.

    On NE passe PAS par `Manager.from_queryset(OwnedQuerySet)` (1) parce que mypy ne
    supporte pas cette base dynamique, et (2) parce que `for_user`/`unscoped` doivent
    de toute façon repartir d'un queryset NON borné (cf. `_unbounded`), sinon elles
    hériteraient du `.none()` de `get_queryset`. On expose donc explicitement les
    deux portes ci-dessous ; le reste du chaînage se fait sur l'OwnedQuerySet renvoyé.
    """

    def get_queryset(self):
        # FAIL-CLOSED : pas de scope explicite → aucune ligne.
        return self._unbounded().none()

    def _unbounded(self):
        # OwnedQuerySet NON borné, construit directement depuis le modèle (et non
        # via get_queryset() qui est .none()). Point de départ de for_user/unscoped.
        return OwnedQuerySet(self.model, using=self._db)

    def for_user(self, user):
        # Contrat inchangé : système (owner NULL) OU perso (owner=user).
        return self._unbounded().for_user(user)

    def unscoped(self):
        # SEUL point de bypass du fail-closed. Accès GLOBAL, auditable par
        # `grep -rn "unscoped(" src/`. Réservé : seeds, admin, commands, import.
        return self._unbounded()


class OwnedBaseManager(models.Manager):
    """
    Base manager NON borné pour les internes Django (`Model._base_manager`).

    Pourquoi : Django utilise `_base_manager` pour résoudre les FK / reverse-FK
    (related descriptors), `dumpdata`, etc. Si on le laissait dériver du manager
    par défaut (OwnedManager, fail-closed), ces lookups internes verraient `.none()`
    et casseraient (ex. `tx.category`, `category.subcategories.all()`).

    Chaque modèle owned déclare donc `Meta.base_manager_name = "_base"` pointant
    sur une instance de CE manager → les internes Django voient TOUTES les lignes,
    tandis que l'accès applicatif via `objects` reste fail-closed.

    ⚠️ NE PAS utiliser ce manager dans du code applicatif : ce n'est PAS un bypass
    auditable. Pour un accès global légitime, utiliser `objects.unscoped()`.
    """

    use_in_migrations = False
