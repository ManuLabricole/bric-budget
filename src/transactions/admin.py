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
    list_display = (
        "date",
        "account",
        "merchant_name",
        "amount",
        "currency",
        "category",
        "categorization_source",
        "is_reconciled",
        "is_ignored",
    )
    list_filter = (
        "account",
        "category",
        "nature",
        "categorization_source",
        "is_reconciled",
        "is_ignored",
        "is_internal_transfer",
        "is_recurring",
    )
    search_fields = ("merchant_name", "description_raw", "note")
    date_hierarchy = "date"
    ordering = ("-date",)
    # readonly_fields: import_hash is generated at import time, never edited manually
    readonly_fields = ("import_hash", "amount_chf")


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
