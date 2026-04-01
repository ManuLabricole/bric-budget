"""
transactions/admin.py — Django admin registration for all transaction models.

Usage during Phase 0B → Phase 1B:
- verify seed categories and subcategories
- inspect imported transactions
- create/edit categorization rules manually
- check import logs when a CSV import fails
- set budget targets per category per month
"""

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


@admin.register(CategorizationRule)
class CategorizationRuleAdmin(admin.ModelAdmin):
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


# =============================================================================
# Transaction
# =============================================================================


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "date",
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
    )
    list_filter = ("account", "status")
    search_fields = ("filename", "file_hash")
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
    )
    ordering = ("-imported_at",)


# =============================================================================
# BudgetTarget
# =============================================================================


@admin.register(BudgetTarget)
class BudgetTargetAdmin(admin.ModelAdmin):
    list_display = ("period", "category", "amount")
    list_filter = ("category",)
    date_hierarchy = "period"
    ordering = ("-period", "category__order")
