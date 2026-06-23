"""
transactions/management/commands/apply_rules.py

Applique toutes les règles de catégorisation actives aux transactions existantes.

Cas d'usage :
  - Après avoir créé ou modifié des règles, pour catégoriser les transactions passées
  - Avant une session de classification manuelle pour réduire le travail restant
  - En routine après un import (l'import le fait déjà, mais de nouvelles règles peuvent
    avoir été ajoutées depuis)

Règle de protection :
  Les transactions catégorisées manuellement (categorization_source="manual") ne sont
  JAMAIS écrasées — elles représentent le choix explicite de l'utilisateur.
  Seules les transactions avec source "default" ou "rule" sont retouchées.

Options :
  --dry-run    Affiche ce qui serait modifié sans écrire en DB
  --limit N    Traite seulement les N premières transactions éligibles (test)
  --reset      Remet category=None sur toutes les transactions non-manuelles avant
               d'appliquer — utile pour "repartir de zéro" après refonte des règles

Usage :
  make apply-rules
  python manage.py apply_rules
  python manage.py apply_rules --dry-run
  python manage.py apply_rules --reset
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from transactions.models import CategorizationRule, Transaction
from transactions.services import ImportService, sync_internal_transfer


class Command(BaseCommand):
    help = "Apply active categorization rules to existing transactions (skips manual)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to DB",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process only the first N eligible transactions (for testing)",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear category/subcategory on non-manual transactions before applying",
        )
        parser.add_argument(
            "--user",
            type=str,
            default=None,
            help=(
                "Email de l'utilisateur : ne traite QUE ses règles (système + perso) et "
                "SES transactions. Sans --user : application GLOBALE (maintenance mono-tenant)."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        reset = options["reset"]

        # ── 0. Résolution du scope user (SR-001 / #205) ──────────────────────────
        # Avec --user : règles for_user(owner) + transactions for_user(owner) → aucune
        # catégorisation croisée. Sans --user : global, donc les règles perso de chaque
        # user pourraient toucher les transactions d'un autre → réservé au mono-tenant.
        owner = None
        user_email = options.get("user")
        if user_email:
            try:
                owner = get_user_model().objects.get(email=user_email)
            except get_user_model().DoesNotExist:
                raise CommandError(f"Utilisateur introuvable : {user_email}")
        else:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Aucun --user : application GLOBALE (toutes les règles → toutes les "
                    "transactions). À n'utiliser qu'en maintenance mono-tenant."
                )
            )

        # ── 1. Charger les règles actives (scopées owner si fourni), par priorité ──
        # Même ordre que dans ImportService.run() — la règle la plus haute gagne.
        rules_qs = (
            CategorizationRule.objects.for_user(owner)
            if owner is not None
            else CategorizationRule.objects.all()
        )
        rules = list(
            rules_qs.filter(is_active=True)
            .select_related("category", "subcategory")
            .order_by("-priority")
        )

        if not rules:
            self.stdout.write(
                self.style.WARNING("Aucune règle active en DB. Rien à faire.")
            )
            return

        self.stdout.write(f"{len(rules)} règles actives chargées.")

        # ── 2. Sélectionner les transactions éligibles ───────────────────────────
        # On exclut "manual" : l'utilisateur a choisi explicitement, on ne touche pas.
        # "default" = pas de règle matchée à l'import → on retente
        # "rule"    = une règle avait matché → on réapplique (une meilleure règle peut exister)
        # SR-001 / #205 : transactions scopées au même owner que les règles (sinon une
        # règle perso de A pourrait catégoriser une transaction de B en mode global).
        base_tx = (
            Transaction.objects.for_user(owner)
            if owner is not None
            else Transaction.objects.all()
        )
        qs = (
            base_tx.exclude(categorization_source="manual")
            .select_related("category", "subcategory")
            .order_by("id")
        )
        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(
            f"{total} transactions éligibles (hors catégorisation manuelle)"
            + ("  [DRY RUN]" if dry_run else "")
            + ("  [RESET]" if reset else "")
        )

        if total == 0:
            return

        # ── 3. Option --reset : effacer les catégories avant de recatégoriser ───
        # Utile si on veut repartir de zéro avec un nouveau jeu de règles.
        # On ne touche jamais aux catégorisations manuelles.
        if reset and not dry_run:
            qs.update(category=None, subcategory=None, categorization_source="default")
            self.stdout.write("Catégories réinitialisées.")
            # Recharger le qs après update (les objets en mémoire sont périmés) — même scope.
            qs = (
                base_tx.exclude(categorization_source="manual")
                .select_related("category", "subcategory")
                .order_by("id")
            )
            if limit:
                qs = qs[:limit]

        # ── 4. Appliquer les règles transaction par transaction ──────────────────
        service = ImportService()

        updated = 0
        unchanged = 0
        batch = []
        BATCH_SIZE = 500

        for tx in qs.iterator(chunk_size=BATCH_SIZE):
            # _find_rule() attend un dict avec display_name et description_raw.
            # On construit un dict minimal — pas besoin d'un vrai TransactionDict complet.
            tx_dict = {
                "display_name": tx.display_name or "",
                "description_raw": tx.description_raw or "",
            }

            matched = service._find_rule(tx_dict, rules)  # type: ignore[arg-type]

            if matched:
                new_cat = matched.category
                new_sub = matched.subcategory
                new_source = "rule"
            else:
                # Aucune règle ne matche → on ne change rien (même catégorie par défaut)
                unchanged += 1
                continue

            # Vérifier si quelque chose change réellement pour éviter un bulk_update inutile
            if tx.category == new_cat and tx.subcategory == new_sub:
                unchanged += 1
                continue

            if dry_run:
                old_cat = tx.category.name if tx.category else "—"
                new_cat_name = new_cat.name if new_cat else "—"
                new_sub_name = new_sub.name if new_sub else "—"
                self.stdout.write(
                    f"  [{tx.id}] {tx.display_name[:50]!r}\n"
                    f"       était : {old_cat}\n"
                    f"       sera  : {new_cat_name}"
                    + (f" › {new_sub_name}" if new_sub else "")
                    + f"  (règle: {matched.keyword!r} p{matched.priority})"
                )
            else:
                tx.category = new_cat
                tx.subcategory = new_sub
                tx.categorization_rule = matched
                tx.categorization_source = new_source
                # Sync virement interne : si la règle catégorise en "virements",
                # is_internal_transfer + is_ignored passent à True automatiquement.
                sync_internal_transfer(tx)
                batch.append(tx)

            updated += 1

            if not dry_run and len(batch) >= BATCH_SIZE:
                Transaction.objects.bulk_update(
                    batch,
                    [
                        "category",
                        "subcategory",
                        "categorization_rule",
                        "categorization_source",
                        "is_internal_transfer",
                        "is_ignored",
                    ],
                )
                batch.clear()
                self.stdout.write(f"  ... {updated} traitées")

        # Flush le dernier batch partiel
        if not dry_run and batch:
            Transaction.objects.bulk_update(
                batch,
                [
                    "category",
                    "subcategory",
                    "categorization_rule",
                    "categorization_source",
                    "is_internal_transfer",
                    "is_ignored",
                ],
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Terminé — {updated} mises à jour, {unchanged} inchangées"
                + (" (dry run, rien sauvegardé)" if dry_run else "")
            )
        )
