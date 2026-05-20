"""
transactions/admin.py — Django admin registration for all transaction models.

Usage during Phase 0B → Phase 1B:
- verify seed categories and subcategories
- inspect imported transactions
- create/edit categorization rules manually
- check import logs when a CSV import fails
- set budget targets per category per month
"""

from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    BudgetTarget,
    CategorizationRule,
    Category,
    ImportLog,
    SubCategory,
    Transaction,
)

# =============================================================================
# SubCategory — shown as inline inside CategoryAdmin
# =============================================================================


class SubCategoryInline(admin.TabularInline):
    """
    TabularInline: renders sub-categories as a table of rows directly
    inside the Category edit page. No need to navigate to a separate page.
    Avoids having to open each subcategory one by one during seed verification.
    """

    model = SubCategory
    extra = 0  # don't show empty placeholder rows by default
    fields = ("name", "slug", "default_nature", "icon", "is_active")
    # prepopulated_fields on inlines requires the parent form's JS — works out of the box
    prepopulated_fields = {"slug": ("name",)}


# =============================================================================
# Category
# =============================================================================


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "colour_hex", "is_system", "is_active")
    list_filter = ("is_system", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order",)
    # inlines: embed the SubCategoryInline table directly on the Category edit page
    inlines = [SubCategoryInline]


# =============================================================================
# SubCategory — also registered standalone for direct access
# =============================================================================


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    # category__name: FK traversal — shows the parent category name
    list_display = ("name", "category", "default_nature", "is_active")
    list_filter = ("category", "default_nature", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


# =============================================================================
# CategorizationRule
# =============================================================================


class CategorizationRuleForm(forms.ModelForm):
    """
    Formulaire custom pour CategorizationRule.

    Pourquoi un custom form ?
        L'admin Django ne filtre pas automatiquement subcategory en fonction
        de category — il montre toutes les sous-catégories. Ce formulaire
        ajoute une validation clean() qui bloque la sauvegarde si la
        sous-catégorie n'appartient pas à la catégorie sélectionnée.
    """

    class Meta:
        model = CategorizationRule
        fields = [
            "keyword",
            "category",
            "subcategory",
            "target_field",
            "priority",
            "is_active",
        ]

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        subcategory = cleaned_data.get("subcategory")
        # Validation : subcategory doit appartenir à category
        if subcategory and category and subcategory.category != category:
            raise forms.ValidationError(
                f"La sous-catégorie « {subcategory.name} » n'appartient pas "
                f"à la catégorie « {category.name} »."
            )
        return cleaned_data


@admin.register(CategorizationRule)
class CategorizationRuleAdmin(admin.ModelAdmin):
    form = CategorizationRuleForm
    list_display = (
        "keyword",
        "target_field",
        "category",
        "subcategory",
        "priority",
        "is_active",
    )
    list_filter = ("target_field", "category", "is_active")
    search_fields = ("keyword",)
    ordering = ("-priority", "keyword")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        Filtre le dropdown subcategory quand on édite une règle existante.

        formfield_for_foreignkey() est appelé pour chaque FK du formulaire.
        On intercepte uniquement "subcategory" et, si l'objet en cours d'édition
        a déjà une catégorie, on restreint le queryset à ses sous-catégories.

        Limitation : fonctionne seulement à l'édition (object_id connu).
        À la création (nouveau formulaire vide), toutes les sous-cats sont affichées
        mais clean() bloque la sauvegarde si le choix est incohérent.
        """
        if db_field.name == "subcategory":
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                try:
                    rule = CategorizationRule.objects.select_related("category").get(
                        pk=object_id
                    )
                    if rule.category:
                        kwargs["queryset"] = SubCategory.objects.filter(
                            category=rule.category, is_active=True
                        ).order_by("name")
                except CategorizationRule.DoesNotExist:
                    pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# =============================================================================
# Transaction
# =============================================================================


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """
    Admin amélioré pour les transactions.

    Liens cliquables :
        account_link  → page admin du compte (Account)
        category_link → page admin de la catégorie
    Ces méthodes retournent du HTML avec format_html() — Django l'injecte tel quel
    dans la colonne, contrairement à une str ordinaire qui serait échappée.
    allow_tags est remplacé par mark_safe/format_html depuis Django 2.0.

    Filtres :
        account__bank  → "Par banque" (proxy pour "par propriétaire" — Yuh=Emmanuel,
                          CIC=Emmanuel FR, etc. Quand Carys aura un compte, son compte
                          apparaîtra ici. Pas de champ owner sur Account pour l'instant.)
        account        → "Par compte" (granularité fine : Courant, Livret A, LDDS…)
        category       → "Par catégorie"
        categorization_source → comment la tx a été catégorisée (auto/règle/manuel)
        is_ignored, is_internal_transfer, is_reconciled, is_recurring → flags booléens

    select_related :
        Déclaré dans get_queryset() pour éviter N+1 — chaque ligne de la liste charge
        account, account__bank et category en un seul JOIN au lieu d'une requête par objet.
    """

    list_display = (
        "date",
        "account_link",
        "display_name",
        "amount",
        "currency",
        "category_link",
        "categorization_source",
        "is_reconciled",
        "is_ignored",
        "is_internal_transfer",
    )
    list_filter = (
        # "Par banque" — proxy propriétaire : Yuh → Emmanuel CH, CIC → Emmanuel FR
        "account__bank",
        # "Par compte" — granularité fine (courant / livret / LDDS…)
        "account",
        # "Par catégorie"
        "category",
        # Source de catégorisation
        "categorization_source",
        # Flags booléens
        "is_ignored",
        "is_internal_transfer",
        "is_reconciled",
        "is_recurring",
        "nature",
    )
    search_fields = ("display_name", "description_raw", "note")
    date_hierarchy = "date"
    ordering = ("-date",)
    readonly_fields = ("import_hash", "amount_chf")

    def get_queryset(self, request):
        """
        Précharge account, account__bank et category en un seul JOIN.
        Sans select_related, chaque ligne de la liste ferait 3 requêtes
        supplémentaires → explosion des requêtes sur une liste de 200 tx.
        """
        return (
            super()
            .get_queryset(request)
            .select_related("account", "account__bank", "category", "subcategory")
        )

    @admin.display(description="Compte", ordering="account__name")
    def account_link(self, obj):
        """
        Lien cliquable vers la page admin du compte.
        reverse("admin:app_model_change", args=[pk]) génère l'URL admin standard.
        format_html() échappe les variables pour éviter les injections XSS.
        """
        if not obj.account:
            return "—"
        url = reverse("admin:accounts_account_change", args=[obj.account.pk])
        return format_html(
            '<a href="{}">{} · {}</a>',
            url,
            obj.account.bank.name if obj.account.bank else "?",
            obj.account.name,
        )

    @admin.display(description="Catégorie", ordering="category__name")
    def category_link(self, obj):
        """
        Lien cliquable vers la page admin de la catégorie.
        Affiche "—" si la transaction n'est pas encore catégorisée.
        """
        if not obj.category:
            return "—"
        url = reverse("admin:transactions_category_change", args=[obj.category.pk])
        label = obj.category.name
        if obj.subcategory:
            label += f" › {obj.subcategory.name}"
        return format_html('<a href="{}">{}</a>', url, label)


# =============================================================================
# ImportLog
# =============================================================================


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = (
        "imported_at",
        "account",
        "filename",
        "status",
        "count_created",
        "count_skipped",
        "count_errors",
        "is_encrypted",
    )
    list_filter = ("account", "status", "is_encrypted")
    search_fields = ("filename", "file_hash", "stored_filename")
    # readonly_fields: everything is auto-generated at import time — nothing editable
    readonly_fields = (
        "account",
        "imported_by",
        "filename",
        "file_hash",
        "imported_at",
        "status",
        "count_created",
        "count_skipped",
        "count_errors",
        "error_detail",
        "stored_filename",
        "stored_path",
        "is_encrypted",
    )
    ordering = ("-imported_at",)


# =============================================================================
# BudgetTarget
# =============================================================================


@admin.register(BudgetTarget)
class BudgetTargetAdmin(admin.ModelAdmin):
    list_display = ("category", "amount")
    list_filter = ("category",)
    ordering = ("category__order",)
