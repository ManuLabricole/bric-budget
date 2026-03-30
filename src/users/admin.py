"""
users/admin.py — Interface admin pour CustomUser et Profile

Pourquoi hériter de UserAdmin et pas ModelAdmin ?
-------------------------------------------------
django.contrib.auth.admin.UserAdmin sait que c'est un utilisateur :
- affiche le password comme "••••••••" avec un lien "changer"
- structure le formulaire en sections (fieldsets)
- gère la confirmation de mot de passe à la création (password1 + password2)

Avec ModelAdmin, le hash du password s'afficherait comme un champ texte brut.
"""

from django.contrib import admin
from django.contrib.auth.admin import (
    UserAdmin,  # la classe de base Django pour les Users
)

from .models import CustomUser, Profile


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    On hérite de UserAdmin pour garder toute la logique password/permissions.
    On redéfinit uniquement ce qui référençait "username" — notre champ supprimé.
    """

    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    # fieldsets = sections du formulaire d'ÉDITION d'un utilisateur existant
    # UserAdmin par défaut met "username" dans la 1ère section — on le remplace par "email"
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Informations personnelles", {"fields": ("first_name", "last_name")}),
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
                "classes": ("collapse",),  # section repliée par défaut
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

    # add_fieldsets = sections du formulaire de CRÉATION (password1 + password2 pour confirmation)
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
    """Profile est un modèle standard — ModelAdmin suffit."""

    list_display = ("user", "langue", "devise_affichage")
    search_fields = (
        "user__email",
    )  # __ = traversée de FK : Profile → CustomUser → email
