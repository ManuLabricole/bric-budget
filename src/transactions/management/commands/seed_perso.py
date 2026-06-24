"""
transactions/management/commands/seed_perso.py — seed PERSO de l'admin (#146).

Seede, pour UN user (Emmanuel par défaut), ses **catégories perso** et ses **règles
de catégorisation exportées de Finary**, scopées `owner=<user>`, `is_system=False`,
puis applique les règles à ses transactions existantes (`apply_rules --user`).

Ce n'est PAS un seed global : contrairement à `seed_categories` (référentiel système
partagé, owner NULL, joué à chaque deploy), `seed_perso` ne touche que les données PERSO
d'un seul user. Idempotente (clé naturelle `(slug|keyword, owner)` → re-run = no-op).

PROD-SAFE (pas de dev-guard) : le but est justement de pouvoir seeder le vrai owner en
prod depuis l'admin (action « Seeder mes règles/catégories perso »). À ne pas confondre
avec `dev_seed` (DEV ONLY, données de démo).

Usage :
    python manage.py seed_perso                       # user = settings.PERSO_SEED_USER_EMAIL
    python manage.py seed_perso --user me@example.com
    python manage.py seed_perso --dry-run             # compte, n'écrit rien
    python manage.py seed_perso --no-apply            # seed sans lancer apply_rules
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from budget.utils import seed_perso_categories
from transactions.models import CategorizationRule, Category, SubCategory

from ._seed_perso_data import FINARY_RULES, PERSO_CATEGORIES

logger = logging.getLogger(__name__)

# Tri « perso d'abord » : owner non-null avant owner NULL (système). Préfère une
# catégorie PERSO du user à une catégorie système de même slug (cf. seed_perso_categories).
_OWNER_PREF = F("owner").asc(nulls_last=True)


def _ensure_perso_rules(user, rules) -> int:
    """Crée (idempotent) les règles perso `rules` pour `user`. Retourne le nombre créé.

    Calqué sur `demo/seeder._ensure_rules`, à une différence près : la cat/subcat visée
    peut être SYSTÈME (owner NULL) **ou PERSO de CE user** (ex. la perso `streaming`).
    On résout donc via `for_user(user)` (système + perso du user), avec préférence perso
    de même slug (`nulls_last` → owner non-null d'abord) — exactement comme
    `seed_perso_categories` choisit son parent. Sans ce tri, `.first()` pourrait viser le
    système alors qu'une perso homonyme existe.
    """
    created = 0
    for keyword, cat_slug, sub_slug, priority in rules:
        # #213 fail-closed : on repart de for_user(user) (le manager nu renverrait .none()).
        category = (
            Category.objects.for_user(user)
            .filter(slug=cat_slug)
            .order_by(_OWNER_PREF)
            .first()
        )
        if category is None:
            # Référentiel système absent (seed_categories pas joué) ou slug obsolète :
            # on saute la règle plutôt que de planter tout le seed. Bruyant dans les logs.
            logger.warning(
                "seed_perso: règle ignorée — catégorie absente : %s", cat_slug
            )
            continue
        subcategory = (
            SubCategory.objects.for_user(user)
            .filter(slug=sub_slug)
            .order_by(_OWNER_PREF)
            .first()
            if sub_slug
            else None
        )
        if sub_slug and subcategory is None:
            # Sous-cat demandée mais introuvable → on garde la règle sur la catégorie seule
            # (mieux qu'aucune règle), en le signalant.
            logger.warning(
                "seed_perso: sous-catégorie absente %s — règle %r posée sur la catégorie seule",
                sub_slug,
                keyword,
            )
        # #213 fail-closed : get_or_create fait son lookup via get_queryset (→ .none()),
        # d'où le queryset scopé for_user pour l'idempotence (sinon re-create → collision).
        _, was_created = CategorizationRule.objects.for_user(user).get_or_create(
            keyword=keyword,
            owner=user,
            defaults={
                "category": category,
                "subcategory": subcategory,
                # Cible CANONIQUE depuis Phase 2G : le display_name (nom propre,
                # agnostique de la banque) — pas description_raw (texte brut, gardé
                # seulement pour rétro-compat des anciennes règles). Un mot-clé Finary
                # match plus fiablement le nom nettoyé que le brut bruité par banque.
                "target_field": CategorizationRule.TargetField.DISPLAY_NAME,
                "priority": priority,
                "is_active": True,
            },
        )
        if was_created:
            created += 1
    return created


class Command(BaseCommand):
    help = (
        "Seed PERSO d'un user (Emmanuel par défaut) : catégories perso + règles Finary "
        "(owner=user, is_system=False), puis apply_rules. Idempotent, prod-safe."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            type=str,
            default=None,
            help=(
                "Email du user à seeder. Défaut : settings.PERSO_SEED_USER_EMAIL "
                "(le propriétaire de l'instance)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait seedé, n'écrit rien.",
        )
        parser.add_argument(
            "--no-apply",
            action="store_true",
            help="Ne lance pas apply_rules après le seed (catégories/règles seulement).",
        )

    def handle(self, *args, **options):
        # ── 1. Résoudre le user cible (par email) ────────────────────────────────
        email = options.get("user") or settings.PERSO_SEED_USER_EMAIL
        if not email:
            raise CommandError(
                "Aucun user cible : passe --user ou renseigne PERSO_SEED_USER_EMAIL (.env)."
            )
        try:
            user = get_user_model().objects.get(email=email)
        except get_user_model().DoesNotExist:
            # Bruyant (exit ≠ 0) : seeder un user inexistant est une erreur d'opérateur.
            raise CommandError(
                f"Utilisateur introuvable : {email}. Crée-le d'abord (create_user)."
            )

        # ── 2. Dry-run : compter sans écrire ─────────────────────────────────────
        if options["dry_run"]:
            n_top = sum(1 for d in PERSO_CATEGORIES if d.parent_slug is None)
            n_sub = sum(1 for d in PERSO_CATEGORIES if d.parent_slug is not None)
            self.stdout.write(
                f"[dry-run] user={email} : {n_top} catégories perso + {n_sub} sous-catégories "
                f"+ {len(FINARY_RULES)} règles seraient seedées — rien n'a été écrit."
            )
            return

        # ── 3. Seed (atomique) : catégories perso + règles ───────────────────────
        # SR-003 : un seed interrompu ne doit jamais laisser les catégories sans leurs
        # règles (ou inversement) — tout ou rien.
        with transaction.atomic():
            n_cat, n_psub = seed_perso_categories(user, PERSO_CATEGORIES)
            n_rules = _ensure_perso_rules(user, FINARY_RULES)

        logger.info(
            "seed_perso user=%s cat=%d sub=%d rules_created=%d",
            email,
            n_cat,
            n_psub,
            n_rules,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ {n_cat} catégories perso + {n_psub} sous-catégories + "
                f"{n_rules} règles créées pour {email}."
            )
        )

        # ── 4. Appliquer les règles aux transactions existantes du user ──────────
        # apply_rules --user scope règles ET transactions à ce owner (#205) → aucune
        # catégorisation croisée. Hors de l'atomic ci-dessus : c'est une 2e passe
        # indépendante (et apply_rules gère sa propre cohérence par batch).
        if not options["no_apply"]:
            self.stdout.write("→ apply_rules sur les transactions existantes…")
            call_command("apply_rules", user=email, stdout=self.stdout)
