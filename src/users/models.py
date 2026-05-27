"""
users/models.py — Custom user model for BricBudget

Why does this file exist?
--------------------------
Django ships with a default User model that uses `username` as the primary
identifier. We want email-based login, so we replace it with our own model.

ABSOLUTE DJANGO RULE: this model must exist BEFORE the first migration.
Changing it after the first migration requires deleting everything and
starting over. That's why AUTH_USER_MODEL is set from day one in settings.py.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager["CustomUser"]):
    """
    Custom manager for CustomUser.

    Why a custom manager?
    ----------------------
    Django's default UserManager calls create_user(username, email, password).
    We removed username — so Django would crash with "missing argument: username".
    This manager replaces that signature, using email as the only identifier.

    A manager is the object that handles DB queries for a model.
    When you write User.objects.create_user(...), this manager is called.
    """

    def create_user(self, email, password=None, **extra_fields):
        """Creates a regular user (is_staff=False, is_superuser=False)."""
        if not email:
            raise ValueError("Email address is required")
        # normalize_email lowercases the domain: Foo@GMAIL.COM → Foo@gmail.com
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        # set_password hashes the password — never store in plain text
        user.set_password(password)  # type: ignore[union-attr]
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Creates a superuser (full access to the Django admin)."""
        # setdefault: only sets the value if the key is not already in extra_fields
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    """
    BricBudget user model.

    We inherit from AbstractUser (not AbstractBaseUser) for a simple reason:
    AbstractUser keeps all the work Django has already done (hashed passwords,
    permissions, groups, is_active, is_staff, date_joined, last_login...).
    We only change the primary identifier: username → email.

    AbstractBaseUser would mean starting from scratch — overkill here.
    """

    # Wire our custom manager — replaces Django's default UserManager
    objects = CustomUserManager()  # type: ignore[misc, assignment]

    # Remove the username field inherited from AbstractUser.
    # None = the field does not exist on our model, not even as a DB column.
    username = None  # type: ignore[assignment]

    # email becomes the primary field — must be unique (no two accounts with the same email)
    email = models.EmailField(unique=True)

    # USERNAME_FIELD tells Django which field to use for authentication.
    # This is what Django checks when someone types their login identifier.
    # Default is "username" — we replace it with "email".
    USERNAME_FIELD = "email"

    # REQUIRED_FIELDS = fields prompted by "createsuperuser" IN ADDITION to USERNAME_FIELD.
    # We clear the list because AbstractUser puts ["email"] there by default,
    # but email is now the USERNAME_FIELD — leaving it here would cause an error.
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email


class Profile(models.Model):
    """
    Extended profile linked to CustomUser — OneToOne relationship.

    Why separate User and Profile?
    --------------------------------
    CustomUser handles authentication (email, password, sessions).
    Profile stores app-level user preferences (language, display currency...).

    OneToOne = exactly 1 Profile per User, exactly 1 User per Profile.
    It's like extending the User table without modifying CustomUser.

    on_delete=CASCADE: deleting the User also deletes their Profile.
    """

    # settings.AUTH_USER_MODEL is the correct way to reference our CustomUser.
    # NEVER write: from django.contrib.auth.models import User
    # NEVER write: ForeignKey("auth.User", ...)
    # Always use: settings.AUTH_USER_MODEL — works even if the User model changes later.
    from django.conf import settings

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",  # allows writing user.profile anywhere in the code
    )

    # Preferred interface language — Emmanuel = fr, Carys = en
    language = models.CharField(
        max_length=10,
        default="fr",
        help_text="BCP 47 language tag: fr, en, de...",
    )

    # Primary display currency — CHF for Emmanuel, GBP for Carys
    display_currency = models.CharField(
        max_length=3,
        default="CHF",
        help_text="ISO 4217 currency code: CHF, EUR, GBP...",
    )

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"

    def __str__(self):
        return f"Profile({self.user.email})"
