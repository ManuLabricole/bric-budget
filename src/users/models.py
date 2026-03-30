"""
users/models.py — Modèle utilisateur custom de BricBudget

Pourquoi ce fichier existe ?
-----------------------------
Django fournit un modèle User par défaut dans django.contrib.auth.
Ce modèle utilise `username` comme identifiant principal.
On veut se connecter par email — donc on doit remplacer ce modèle par le nôtre.

RÈGLE ABSOLUE Django : ce modèle doit exister AVANT la première migration.
Si on change d'avis après avoir migré, il faut tout supprimer et recommencer.
C'est pourquoi AUTH_USER_MODEL est défini dès le départ dans settings.py.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager):
    """
    Manager custom pour CustomUser.

    Pourquoi ce Manager ?
    ----------------------
    Le UserManager par défaut de Django appelle create_user(username, email, password).
    On a supprimé username — donc Django plante avec "missing argument: username".
    Ce Manager remplace la signature pour utiliser email comme seul identifiant.

    Un Manager, c'est l'objet qui gère les requêtes DB pour un modèle.
    Quand tu écris User.objects.create_user(...), c'est ce Manager qui est appelé.
    """

    def create_user(self, email, password=None, **extra_fields):
        """Crée un utilisateur normal (is_staff=False, is_superuser=False)."""
        if not email:
            raise ValueError("L'adresse email est obligatoire")
        # normalize_email met le domaine en minuscules : Foo@GMAIL.COM → Foo@gmail.com
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        # set_password hashe le mot de passe — jamais stocker en clair
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Crée un superuser (accès complet à l'admin Django)."""
        # setdefault : met la valeur seulement si la clé n'est pas déjà dans extra_fields
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    """
    Modèle utilisateur de BricBudget.

    On hérite de AbstractUser (pas AbstractBaseUser) pour une raison simple :
    AbstractUser garde tout le travail déjà fait par Django (password hashé,
    permissions, groupes, is_active, is_staff, date_joined, last_login...).
    On se contente de changer l'identifiant principal : username → email.

    AbstractBaseUser serait pour repartir de zéro — overkill ici.
    """

    # Branche notre Manager custom — remplace le UserManager par défaut de Django
    objects = CustomUserManager()

    # On supprime le champ username hérité de AbstractUser.
    # None = le champ n'existe pas dans notre modèle, même pas comme colonne en DB.
    username = None

    # L'email devient le champ principal — il doit être unique (pas deux comptes avec le même email).
    email = models.EmailField(
        unique=True,
        verbose_name="adresse email",
    )

    # USERNAME_FIELD dit à Django quel champ utiliser pour l'authentification.
    # C'est ce que Django vérifie quand quelqu'un tape son identifiant à la connexion.
    # Par défaut c'est "username" — on le remplace par "email".
    USERNAME_FIELD = "email"

    # REQUIRED_FIELDS = champs demandés par "createsuperuser" EN PLUS de USERNAME_FIELD.
    # On vide la liste car AbstractUser y met ["email"] par défaut,
    # mais email est maintenant le USERNAME_FIELD — le laisser ici ferait une erreur.
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"

    def __str__(self):
        # Représentation lisible dans l'admin et les logs
        return self.email


class Profile(models.Model):
    """
    Profil étendu lié à CustomUser — relation OneToOne.

    Pourquoi séparer User et Profile ?
    -----------------------------------
    CustomUser gère l'authentification (email, password, sessions).
    Profile stocke les préférences métier de l'app (langue, devise d'affichage...).

    OneToOne = exactement 1 Profile par User, exactement 1 User par Profile.
    C'est comme une extension de la table User sans modifier CustomUser.

    on_delete=CASCADE : si on supprime le User, son Profile est supprimé aussi.
    """

    # settings.AUTH_USER_MODEL est la bonne façon de référencer notre CustomUser.
    # Ne JAMAIS écrire : from django.contrib.auth.models import User
    # Ne JAMAIS écrire : ForeignKey("auth.User", ...)
    # Toujours : settings.AUTH_USER_MODEL — ça fonctionne même si on change le modèle User plus tard.
    from django.conf import settings
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",  # permet d'écrire user.profile depuis n'importe où dans le code
    )

    # Langue préférée de l'interface — Emmanuel = fr, Carys = en (GB)
    langue = models.CharField(
        max_length=10,
        default="fr",
        verbose_name="langue de l'interface",
    )

    # Devise d'affichage principale — CHF pour Emmanuel, GBP pour Carys
    devise_affichage = models.CharField(
        max_length=3,
        default="CHF",
        verbose_name="devise d'affichage",
        help_text="Code ISO 4217 : CHF, EUR, GBP...",
    )

    class Meta:
        verbose_name = "profil"
        verbose_name_plural = "profils"

    def __str__(self):
        return f"Profil de {self.user.email}"
