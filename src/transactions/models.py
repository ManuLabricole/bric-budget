"""
transactions/models.py — Financial flows for BricBudget

Model dependency order:
    Category
      └── SubCategory
            └── CategorizationRule  (keyword → Category + SubCategory)
    Account (from accounts/) → Transaction → Category + SubCategory
                                           → self (paired_transaction)
    BudgetTarget → Category
    BudgetResult → BudgetTarget
    ImportLog    → Account
"""

from django.conf import settings
from django.db import models

# OwnedManager / OwnedQuerySet (manager fail-closed #213) vivent désormais dans
# transactions/managers.py — source de vérité unique du scoping par owner.
from .managers import OwnedBaseManager, OwnedManager

# =============================================================================
# Category — Top-level spending category
# =============================================================================


class Category(models.Model):
    """
    Top-level budget category: Food & Drinks, Transport, Housing...

    is_system = True: category seeded at setup, cannot be deleted or renamed.
    Two system categories must always exist:
        - "Unknown"   → default when no categorization rule matches a transaction
        - "Transfers" → internal transfers between personal accounts

    Why is_system matters: Transaction.category uses on_delete=SET_DEFAULT,
    meaning if a user deletes a custom category all its transactions fall back
    to "Unknown". That fallback only works if "Unknown" can never be deleted.

    No `nature` here — nature (fixed/variable/income...) lives on Transaction,
    with SubCategory.default_nature as a suggestion at categorization time.
    """

    # name / slug — unicité SCOPÉE par owner (issue #137).
    #   Système (owner IS NULL) : unique GLOBAL — un seul "inconnu", un seul "revenus".
    #   Perso   (owner set)     : unique PAR USER — chaque user peut avoir sa propre
    #                             catégorie "Restaurants" sans collision.
    # unique=True (global) retiré ici → remplacé par les UniqueConstraint partielles
    # de Meta.constraints (cf. migration 0018). Garder unique=True ici rendrait
    # impossible le multi-user (deux "Restaurants" → IntegrityError).
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)

    # Icon identifier — maps to static/icons/categories/<icon>.svg
    # Example: "auto-transport", "food-drinks", "housing"
    # blank=True: falls back to a generic icon in templates
    icon = models.CharField(max_length=50, blank=True, default="")

    # Hex colour for charts and badges — e.g. "#F97316" (orange)
    # blank=True: falls back to a default colour in templates
    colour_hex = models.CharField(max_length=7, blank=True, default="")

    # Display order in lists and charts (lower = first)
    order = models.PositiveSmallIntegerField(default=0)

    # is_system=True: seeded at setup, cannot be deleted/renamed by the user
    is_system = models.BooleanField(default=False)

    # owner — propriétaire de la catégorie (issue #137, isolation multi-user).
    #   NULL  : catégorie SYSTÈME, partagée entre tous les users (is_system=True).
    #   sinon : catégorie PERSO d'un user (is_system=False) — jamais visible par
    #           un autre user (filtrée via .for_user()).
    # SET_NULL : supprimer un user ne doit pas effacer ses catégories perso ni les
    #   transactions qui y pointent ; elles deviennent orphelines (owner NULL) plutôt
    #   que d'être détruites en cascade. on_delete=CASCADE serait une perte de données.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categories",
    )

    is_active = models.BooleanField(default=True)

    # Manager fail-closed (#213) : .objects.all() → .none() ; scope explicite requis
    # via .for_user(user) ou .unscoped(). Voir transactions/managers.py.
    objects = OwnedManager()
    # Base manager NON borné pour les internes Django (FK/reverse-FK, dumpdata).
    _base = OwnedBaseManager()

    class Meta:
        # Les internes Django (related lookups) passent par _base, PAS par le
        # fail-closed `objects` → tx.category, category.subcategories.all() OK.
        base_manager_name = "_base"
        verbose_name = "category"
        verbose_name_plural = "categories"
        ordering = ["order", "name"]
        constraints = [
            # Système (owner NULL) : slug/name uniques GLOBALEMENT.
            # Pourquoi une contrainte partielle dédiée plutôt que (owner, slug) ?
            # En Postgres les NULL sont distincts dans un UNIQUE → (owner, slug)
            # n'empêcherait PAS deux système "inconnu". On force donc l'unicité
            # globale uniquement sur les lignes owner IS NULL.
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(owner__isnull=True),
                name="category_system_slug_uniq",
            ),
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(owner__isnull=True),
                name="category_system_name_uniq",
            ),
            # Perso (owner set) : slug/name uniques PAR USER. Deux users peuvent
            # chacun avoir "Restaurants" ; un même user ne peut pas le dupliquer.
            models.UniqueConstraint(
                fields=["owner", "slug"],
                condition=models.Q(owner__isnull=False),
                name="category_owner_slug_uniq",
            ),
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=models.Q(owner__isnull=False),
                name="category_owner_name_uniq",
            ),
        ]

    def __str__(self):
        return self.name


# =============================================================================
# SubCategory — Second-level category
# =============================================================================


class SubCategory(models.Model):
    """
    Sub-category under a Category.

    Example: Category "Transport" → SubCategories "Gas", "Parking", "Train"...

    default_nature: the budget nature pre-filled on a transaction when it is
    assigned this sub-category. The user can override it per transaction.
    "Apply to all" in the UI runs:
        Transaction.objects.filter(subcategory=this).update(nature=this.default_nature)

    Sub-category is always optional on a transaction — a transaction can have
    a category without a sub-category (common when auto-categorised).
    """

    class Nature(models.TextChoices):
        INCOME = "income", "Income"
        FIXED_MANDATORY = "fixed_mandatory", "Fixed mandatory"
        FIXED_DISCRETIONARY = "fixed_discretionary", "Fixed discretionary"
        VARIABLE_MANDATORY = "variable_mandatory", "Variable mandatory"
        VARIABLE_DISCRETIONARY = "variable_discretionary", "Variable discretionary"
        SAVINGS = "savings", "Savings"

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,  # CASCADE: deleting a category removes its sub-categories
        related_name="subcategories",
    )

    name = models.CharField(max_length=100)
    # slug — unicité scopée par owner (issue #137), comme Category.
    #   Système (owner NULL) : unique global ; Perso : unique par user.
    # unique=True (global) retiré → UniqueConstraint partielles en Meta.
    slug = models.SlugField(max_length=100)

    # Icon identifier — maps to static/icons/categories/<icon>.svg
    # Example: "auto-transport", "food-drinks", "housing"
    # blank=True: falls back to a generic icon in templates
    icon = models.CharField(max_length=50, blank=True, default="")

    # Suggested nature for transactions in this sub-category.
    # blank=True: not all sub-categories need a default (e.g. "Unknown")
    default_nature = models.CharField(
        max_length=30,
        choices=Nature.choices,
        blank=True,
        default="",
    )

    is_active = models.BooleanField(default=True)

    # is_system=True: seeded at setup, cannot be deleted/renamed by the user.
    # is_system=False: created by the user in the UI — shown with a "perso" badge.
    # Mirrors Category.is_system but at the sub-category level.
    is_system = models.BooleanField(default=False)

    # owner — même sémantique que Category.owner (issue #137) :
    #   NULL = système partagé ; sinon = perso d'un user, jamais visible par un autre.
    # SET_NULL : ne pas casser les transactions liées si le user est supprimé.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subcategories",
    )

    # Manager fail-closed (#213) : .objects.all() → .none() ; scope via .for_user/.unscoped.
    objects = OwnedManager()
    _base = OwnedBaseManager()  # internes Django (FK/reverse-FK)

    class Meta:
        base_manager_name = "_base"
        verbose_name = "sub-category"
        verbose_name_plural = "sub-categories"
        ordering = ["category__order", "name"]
        constraints = [
            # Nom unique par sous-catégorie d'une catégorie — SCOPÉ owner (#137).
            # ⚠️ L'ancienne contrainte plate (category, name) supposait à tort qu'une
            # perso a toujours un parent distinct par user : FAUX, une perso peut vivre
            # sous une catégorie SYSTÈME (partagée, ex. « Concert » sous « Loisirs »).
            # On scinde donc comme Category : système global, perso par user.
            models.UniqueConstraint(
                fields=["category", "name"],
                condition=models.Q(owner__isnull=True),
                name="subcategory_system_category_name_uniq",
            ),
            models.UniqueConstraint(
                fields=["category", "name", "owner"],
                condition=models.Q(owner__isnull=False),
                name="subcategory_owner_category_name_uniq",
            ),
            # slug — système (owner NULL) unique global ; perso unique par user.
            # Même raisonnement que Category : contrainte partielle dédiée au
            # système car les NULL sont distincts dans un UNIQUE Postgres.
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(owner__isnull=True),
                name="subcategory_system_slug_uniq",
            ),
            models.UniqueConstraint(
                fields=["owner", "slug"],
                condition=models.Q(owner__isnull=False),
                name="subcategory_owner_slug_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.category.name} › {self.name}"


# =============================================================================
# CategorizationRule — Keyword → Category mapping
# =============================================================================


class CategorizationRule(models.Model):
    """
    Auto-categorisation rule: if a transaction's target field contains `keyword`,
    assign it `category` (and optionally `subcategory`).

    How categorisation works at import time:
    1. For each new transaction, iterate rules ordered by `priority` (desc).
    2. Check if `keyword` appears in the transaction field defined by `target_field`.
    3. First match wins → assign category + subcategory.
    4. No match → assign the "Unknown" system category.
    5. Claude API fallback (Phase 6) if too many unknowns accumulate.

    After creating or editing a rule, the UI offers "Apply to existing transactions"
    — this triggers a bulk re-categorisation query.

    target_field: which transaction field to search.
    "description_raw" = the raw bank text (never edited).
    "merchant_name"   = the cleaned merchant name (may have been edited by user).
    Matching on merchant_name lets rules benefit from previous manual corrections.
    """

    class TargetField(models.TextChoices):
        DESCRIPTION_RAW = "description_raw", "Raw description"
        MERCHANT_NAME = "merchant_name", "Merchant name (legacy)"
        # display_name is the stored cleaned bank-agnostic name — canonical target since Phase 2G.
        DISPLAY_NAME = "display_name", "Display name (clean)"

    keyword = models.CharField(max_length=200)

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,  # CASCADE: deleting a category removes its rules
        related_name="rules",
    )

    # subcategory is optional — a rule can assign a category without a sub-category
    subcategory = models.ForeignKey(
        SubCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rules",
    )

    target_field = models.CharField(
        max_length=20,
        choices=TargetField.choices,
        default=TargetField.DISPLAY_NAME,
    )

    # Higher priority = checked first. Rules with the same priority are checked
    # in insertion order (no guaranteed tie-breaking — keep priorities unique).
    priority = models.PositiveSmallIntegerField(default=0)

    is_active = models.BooleanField(default=True)

    # owner — propriétaire de la règle (issue #145, isolation multi-user / IDOR SR-001).
    #   NULL  : règle SYSTÈME, partagée entre tous les users (seed de référence).
    #   sinon : règle PERSO d'un user — jamais visible/modifiable par un autre
    #           (filtrée via .for_user()).
    # CASCADE (≠ Category.owner=SET_NULL) : une règle est une préférence pure de
    #   catégorisation. Supprimer un user n'a aucune raison de garder ses règles
    #   perso orphelines (elles ne portent aucune donnée historique, contrairement
    #   aux catégories pointées par des transactions). On les efface avec lui.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="categorization_rules",
    )

    # Manager fail-closed (#213) : .objects.all() → .none() ; scope via .for_user/.unscoped.
    objects = OwnedManager()
    _base = OwnedBaseManager()  # internes Django (FK/reverse-FK)

    class Meta:
        base_manager_name = "_base"
        verbose_name = "categorization rule"
        verbose_name_plural = "categorization rules"
        ordering = ["-priority", "keyword"]

    def __str__(self):
        target = f"[{self.target_field}]"
        dest = str(self.subcategory) if self.subcategory else str(self.category)
        return f'"{self.keyword}" {target} → {dest}'


# =============================================================================
# TransactionQuerySet — Queryset manager avec filtre de sécurité par user
# =============================================================================


class TransactionQuerySet(models.QuerySet):
    """
    QuerySet custom pour Transaction.

    Méthode principale : .for_user(user)
        Filtre les transactions selon les comptes dont l'utilisateur est membre.
        À appeler en premier sur toutes les requêtes exposées dans les vues :

            Transaction.objects.for_user(request.user).filter(date__gte=...)

        Pourquoi un QuerySet et pas un filtre inline dans chaque vue ?
            - DRY : 17 endroits dans views.py touchent Transaction.objects — un seul
              point de vérité évite les oublis.
            - Sécurité : si on ajoute un champ 'members' à Account, le filter est
              mis à jour ici et toutes les vues bénéficient du fix automatiquement.
            - Chainable : retourne un QuerySet → on peut chaîner .filter(), .exclude(),
              .order_by()... sans friction.
    """

    def for_user(self, user):
        """
        Retourne uniquement les transactions des comptes dont `user` est membre.

        Utilise le M2M Account.members → filtre via __members qui traverse
        la table de jonction accounts_account_members.
        Un user non-membre d'aucun compte obtient un queryset vide.
        """
        return self.filter(account__members=user)


# =============================================================================
# Transaction — A single financial movement on an account
# =============================================================================


class Transaction(models.Model):
    """
    A single financial movement: debit or credit on an account.

    Amount convention: negative = money out (debit), positive = money in (credit).
    Example: -9.99 CHF = you spent 9.99, +3500 CHF = salary received.

    description_raw: the raw text from the bank export. Never modified — it's
    the audit trail. Used by CategorizationRule matching (target_field=description_raw).

    merchant_name: cleaned display name, editable by the user.
    Example: "COOP-2347 LAUSANNE VD" → "Coop Lausanne". This is what shows in the UI.
    Also used by CategorizationRule matching (target_field=merchant_name), so manual
    corrections benefit future auto-categorisation.

    categorization_source: tracks HOW the category was assigned.
    Displayed in the UI as "RULE APPLIED" or "AI CATEGORIZED" badges (cf. Finary).
    When the user manually changes the category, source becomes "manual" and
    categorization_rule is cleared.

    is_ignored: excludes the transaction from ALL budget calculations and charts.
    The toggle in the UI is labelled "Inclure dans l'analyse budgétaire" — it's
    the inverse of this field (toggle ON = is_ignored False = included).

    is_recurring: marks the transaction as a recurring charge (subscription, rent...).
    Set manually for now — Phase 3B will add automatic detection via merchant + frequency.

    paired_transaction: links both sides of an internal transfer.
    Example: Emmanuel sends 500 CHF from Yuh to CIC → two transactions, each
    pointing to the other via paired_transaction. Both are marked is_internal_transfer=True.
    """

    # --- Account & card ---

    account = models.ForeignKey(
        "accounts.Account",  # string reference — avoids cross-app circular imports
        on_delete=models.PROTECT,  # PROTECT: don't silently lose transactions if account deleted
        related_name="transactions",
    )

    card = models.ForeignKey(
        "accounts.Card",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        # null when transaction has no card: salary, bank fees, standing orders...
    )

    # --- Categorisation ---

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        # null = uncategorised, treated as "Unknown" in queries and templates
    )

    subcategory = models.ForeignKey(
        SubCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    # Re-uses the same TextChoices as SubCategory.default_nature.
    # Source of truth for budget analysis — pre-filled from subcategory.default_nature
    # at categorisation time, overridable per transaction.
    # blank=True: not set until the transaction is categorised.
    nature = models.CharField(
        max_length=30,
        choices=SubCategory.Nature.choices,
        blank=True,
        default="",
    )

    class CategorizationSource(models.TextChoices):
        DEFAULT = "default", "Default (Unknown)"  # no rule matched
        RULE = "rule", "Rule applied"  # auto-matched by a CategorizationRule
        AI = "ai", "AI categorized"  # Claude API fallback (Phase 6)
        MANUAL = "manual", "Manual"  # user picked the category themselves

    categorization_source = models.CharField(
        max_length=10,
        choices=CategorizationSource.choices,
        default=CategorizationSource.DEFAULT,
    )

    # Which rule triggered the categorisation — shown in the UI detail panel.
    # Cleared when the user manually overrides the category.
    categorization_rule = models.ForeignKey(
        CategorizationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    # --- Amounts ---

    date = models.DateField()

    # Time of the transaction — provided by some banks (UBS: "12:36:26"), absent in others
    # (Yuh, CIC). null=True because most banks don't export the time.
    # Useful for creating precise categorization rules and debugging duplicate transactions
    # on the same day with the same amount.
    time = models.TimeField(null=True, blank=True)

    # Negative = debit (money out), positive = credit (money in)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    # ISO 4217 currency code of the account — CHF, EUR, GBP...
    currency = models.CharField(max_length=3)

    # Amount converted to CHF via ExchangeRate — for consolidated charts.
    # null until the exchange rate for this date is loaded.
    amount_chf = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )

    # --- Description ---

    # Raw text from the bank export — never modified, used for audit trail only.
    description_raw = models.CharField(max_length=500)

    # Bank-agnostic cleaned description — computed at import by _clean_description()
    # in connectors/base.py. Stored so the ORM can filter on it (categorization rules,
    # search, keyword_q). Recomputable via `make recalculate-display-names`.
    display_name = models.CharField(max_length=300, blank=True, default="")

    # User-editable override — shown instead of display_name when set.
    # Pre-filled from display_name at import; user can rename ("Loyer Robert" etc.).
    merchant_name = models.CharField(max_length=200, blank=True, default="")

    # Free-text note added by the user — e.g. "January rent", "wedding gift"
    note = models.TextField(blank=True, default="")

    # --- Status flags ---

    # Verified against the bank statement — "Pointer la transaction" in the UI
    is_reconciled = models.BooleanField(default=False)

    # Excluded from all budget calculations and charts
    # UI toggle is "Inclure dans l'analyse budgétaire" = NOT is_ignored
    is_ignored = models.BooleanField(default=False)

    # Marks a recurring charge: subscription, rent, insurance...
    # Auto-detection planned in Phase 3B (same merchant + regular frequency)
    is_recurring = models.BooleanField(default=False)

    # Internal transfer between two personal accounts
    is_internal_transfer = models.BooleanField(default=False)

    # Links both sides of an internal transfer — FK to self
    # symmetrical=False is implicit on FK (only ManyToMany has symmetrical)
    paired_transaction = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paired_by",
    )

    # --- Import ---

    # SHA256 hash of the raw row — used at import time to skip duplicates.
    # unique=True: Django raises IntegrityError if the same row is imported twice.
    # max_length=64: SHA256 hex digest is always 64 characters.
    import_hash = models.CharField(max_length=64, unique=True)

    # Lien vers l'import qui a créé cette transaction.
    # null=True : permet aux transactions créées en CLI (sans ImportLog) de rester valides.
    # CASCADE : supprimer un ImportLog supprime automatiquement toutes ses transactions.
    import_log = models.ForeignKey(
        "ImportLog",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="transactions",
    )

    # Manager custom — remplace Transaction.objects par le QuerySet ci-dessus.
    # as_manager() expose toutes les méthodes du QuerySet comme méthodes du manager.
    # Transaction.objects.for_user(user) fonctionne comme Transaction.objects.filter(...)
    objects = TransactionQuerySet.as_manager()

    class Meta:
        verbose_name = "transaction"
        verbose_name_plural = "transactions"
        ordering = ["-date", "-id"]

    def __str__(self):
        direction = "→" if self.amount < 0 else "←"
        name = self.merchant_name or self.description_raw[:40]
        return f"{self.date} {direction} {abs(self.amount)} {self.currency} | {name}"


# =============================================================================
# ImportLog — Record of a single CSV/file import session
# =============================================================================


class ImportLog(models.Model):
    """
    One row per import session — created every time a file is uploaded.

    Answers the question "what happened when I imported this file?" without
    having to query the transactions table.

    stats are stored as plain integer fields (not JSON) to keep queries simple:
    you can do ImportLog.objects.filter(count_errors__gt=0) without JSON parsing.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial (some errors)"
        FAILED = "failed", "Failed"

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="import_logs",
    )

    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="import_logs",
    )

    # Original filename — useful for debugging and for Yuh balance extraction
    # (balance is encoded in the filename: "Activités_2026_03_17 - 33,344.CSV")
    filename = models.CharField(max_length=255)

    # hex digest — prevents importing the exact same file twice per account.
    # Algorithm mixte selon le connecteur :
    #   SHA1(contenu brut) → 40 chars  — fichiers mono-feuille (Yuh, UBS)
    #   SHA256(sha1:sheet) → 64 chars  — fichiers multi-feuilles (CIC, 1 log par feuille)
    # max_length=64 couvre les deux cas.
    # Contrainte per-account (pas globale) : deux users peuvent importer le même fichier.
    file_hash = models.CharField(max_length=64)

    imported_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.SUCCESS,
    )

    # Import stats — stored as plain integers for easy filtering
    count_created = models.PositiveIntegerField(default=0)  # new transactions inserted
    count_skipped = models.PositiveIntegerField(
        default=0
    )  # duplicates (hash already exists)
    count_errors = models.PositiveIntegerField(default=0)  # rows that failed to parse

    # Optional error detail for debugging — populated when status != SUCCESS
    error_detail = models.TextField(blank=True, default="")

    # ── Stockage permanent du fichier source ──────────────────────────────────
    # Renseigné après confirmation de l'import (vide pour les imports CLI).
    #
    # stored_filename : nom canonique calculé depuis les métadonnées du fichier.
    #   Convention : {bank}_{account}_{date_min}_{date_max}[_b{balance}]_{n}tx{ext}
    #   Exemple    : yuh_checking_20260101_20260430_b12345.67_42tx.csv
    #
    # stored_path : chemin RELATIF à settings.IMPORT_STORAGE_ROOT.
    #   On ne stocke jamais de chemin absolu en DB — non portable entre machines.
    #   Exemple    : yuh/2026/yuh_checking_20260101_20260430_b12345.67_42tx.csv.enc
    #
    # is_encrypted : True si le fichier est chiffré avec Fernet.
    #   Tous les nouveaux imports web sont chiffrés (clé dans .env).
    stored_filename = models.CharField(max_length=255, blank=True, default="")
    stored_path = models.CharField(max_length=500, blank=True, default="")
    is_encrypted = models.BooleanField(default=False)

    # Date range of the transactions in this import — populated after bulk_create.
    # None for failed imports (0 transactions created) or legacy CLI imports.
    date_min = models.DateField(null=True, blank=True)
    date_max = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "import log"
        verbose_name_plural = "import logs"
        ordering = ["-imported_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["file_hash", "account"],
                name="importlog_file_hash_account_uniq",
            )
        ]

    def __str__(self):
        return f"{self.imported_at:%Y-%m-%d %H:%M} | {self.account} | {self.filename} ({self.status})"


# =============================================================================
# BudgetTarget — Monthly spending target per category
# =============================================================================


class BudgetTarget(models.Model):
    """
    A monthly spending target for a category — applies to every month.

    One target per category (no period). The target is a general monthly setting:
    "I want to spend at most 500 CHF/month on Alimentation."

    When viewing a 3-month or 1-year period, the view multiplies by the number of
    months to get the scaled target.

    The actual result is NOT stored — computed live from transactions.
    amount is always in CHF.
    """

    # category — un objectif vise UNE catégorie. ⚠️ Avant #201 c'était un OneToOneField
    # → un seul objectif GLOBAL par catégorie. Sur une catégorie SYSTÈME (partagée), ça
    # voulait dire un objectif unique partagé/écrasable entre TOUS les users (write
    # cross-user). On passe en ForeignKey + unicité scopée (owner, category) ci-dessous.
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="budget_targets",
    )

    # owner — propriétaire de l'objectif (issue #201). Un objectif est TOUJOURS perso :
    # il n'existe pas d'objectif « système » partagé (contrairement à Category/SubCategory).
    # owner non-null + UniqueConstraint(owner, category) = chaque user a SON objectif sur
    # une catégorie donnée, y compris sur une catégorie système, sans collision ni fuite.
    # CASCADE : supprimer un user efface ses objectifs (pure préférence, aucune donnée
    # historique pointée).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="budget_targets",
    )

    # Target monthly spend in CHF
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    # Manager fail-closed (#213) : .objects.all() → .none() ; scope via .for_user/.unscoped.
    # owner étant non-null, for_user se réduit à owner=user (branche owner__isnull=True
    # morte ici, mais on réutilise le même point de vérité pour rester cohérent).
    objects = OwnedManager()
    _base = OwnedBaseManager()  # internes Django (FK/reverse-FK)

    class Meta:
        base_manager_name = "_base"
        verbose_name = "budget target"
        verbose_name_plural = "budget targets"
        ordering = ["category__order"]
        constraints = [
            # Un objectif par (user, catégorie) — remplace l'unique implicite du OneToOne.
            models.UniqueConstraint(
                fields=["owner", "category"],
                name="budgettarget_owner_category_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.category} → {self.amount} CHF/month (owner={self.owner_id})"
