"""
accounts/admin.py — Django admin registration for all banking models.

Why configure the admin at all?
--------------------------------
The Django admin is our main tool for Phase 0B → Phase 1A:
- verify that seed data was inserted correctly
- manually create/edit banks, accounts, cards for setup
- inspect BalanceSnapshots and ExchangeRates after imports
- debug import issues before the proper UI exists (Phase 1B)

Registration order follows the model dependency chain:
    Bank → Account → CheckingAccount → Card
                   → BalanceSnapshot
    ExchangeRate (standalone)
"""

from django.contrib import admin

from .models import (
    Account,
    BalanceSnapshot,
    Bank,
    Card,
    CheckingAccount,
    ExchangeRate,
    SavingsAccount,
)

# =============================================================================
# Bank
# =============================================================================


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "default_currency", "icon_slug", "is_active")
    list_filter = ("country", "is_active")
    search_fields = ("name", "slug")
    # prepopulated_fields: when you type the name, Django auto-fills the slug field.
    # Works via a small JavaScript snippet injected by the admin — no JS to write.
    prepopulated_fields = {"slug": ("name",)}


# =============================================================================
# Account
# =============================================================================


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "bank", "account_type", "currency", "is_active")
    list_filter = ("bank", "account_type", "currency", "is_active")
    search_fields = ("name",)


# =============================================================================
# CheckingAccount — shown inline under Account in a real setup,
# but registered standalone here so we can inspect IBAN/BIC directly.
# =============================================================================


@admin.register(CheckingAccount)
class CheckingAccountAdmin(admin.ModelAdmin):
    # account__name: FK traversal — shows the linked Account's name in the list
    list_display = ("account", "iban", "bic")
    search_fields = ("account__name", "iban")


# =============================================================================
# SavingsAccount
# =============================================================================


@admin.register(SavingsAccount)
class SavingsAccountAdmin(admin.ModelAdmin):
    list_display = ("account", "interest_rate", "account_reference")
    search_fields = ("account__name", "account_reference")


# =============================================================================
# Card
# =============================================================================


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("last_four", "card_type", "checking_account", "user", "is_active")
    list_filter = ("card_type", "is_active")
    search_fields = ("last_four", "user__email")


# =============================================================================
# BalanceSnapshot
# =============================================================================


@admin.register(BalanceSnapshot)
class BalanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("account", "date", "balance", "currency", "balance_chf", "source")
    list_filter = ("account", "source", "currency")
    # date_hierarchy: adds a date drill-down bar at the top of the list (year → month → day)
    date_hierarchy = "date"
    ordering = ("-date",)


# =============================================================================
# ExchangeRate
# =============================================================================


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("date", "from_currency", "to_currency", "rate")
    list_filter = ("from_currency", "to_currency")
    date_hierarchy = "date"
    ordering = ("-date",)
