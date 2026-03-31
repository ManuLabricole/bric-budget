"""
users/admin.py — Django admin registration for CustomUser and Profile

Why inherit from UserAdmin instead of ModelAdmin?
-------------------------------------------------
django.contrib.auth.admin.UserAdmin knows it's dealing with a user model:
- displays the password as "••••••••" with a "change" link
- structures the form into sections (fieldsets)
- handles password confirmation on creation (password1 + password2)

With plain ModelAdmin, the password hash would render as a raw text field.
"""

from django.contrib import admin
from django.contrib.auth.admin import (
    UserAdmin,  # Django's base class for user models
)

from .models import CustomUser, Profile


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    Inherits from UserAdmin to keep all password/permission logic.
    We only redefine the parts that referenced "username" — our removed field.
    """

    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    # fieldsets = sections of the EDIT form for an existing user
    # UserAdmin default puts "username" in the first section — we replace it with "email"
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal information", {"fields": ("first_name", "last_name")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
                "classes": ("collapse",),  # section collapsed by default
            },
        ),
        (
            "Dates",
            {
                "fields": ("last_login", "date_joined"),
                "classes": ("collapse",),
            },
        ),
    )

    # add_fieldsets = sections of the CREATE form (password1 + password2 for confirmation)
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Profile is a standard model — ModelAdmin is sufficient."""

    list_display = ("user", "language", "display_currency")
    search_fields = (
        "user__email",
    )  # __ = FK traversal: Profile → CustomUser → email
