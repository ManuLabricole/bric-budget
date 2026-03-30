"""
users/management/commands/create_user.py

Commande Django custom : crée un utilisateur depuis les variables .env.

Pourquoi une commande custom ?
-------------------------------
`manage.py createsuperuser` est interactif — il pose des questions à chaque fois.
Inutilisable dans un script ou après un reset DB.
Cette commande lit les credentials depuis .env et crée l'utilisateur en une ligne.

Usage :
    python manage.py create_user                   # crée un user normal
    python manage.py create_user --superuser       # crée un superuser

Variables .env requises :
    SUPERUSER_EMAIL=ton@email.com
    SUPERUSER_PASSWORD=ton_mot_de_passe

Pattern Django — toute commande custom hérite de BaseCommand et implémente :
    - add_arguments() : déclare les arguments CLI (optionnels)
    - handle()        : le code qui s'exécute quand on lance la commande
"""

from decouple import config
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    # Description affichée par `python manage.py help create_user`
    help = "Crée un utilisateur (ou superuser) depuis les variables d'environnement .env"

    def add_arguments(self, parser):
        """
        Déclare les arguments optionnels de la commande.
        `parser` est un ArgumentParser Python standard.
        """
        parser.add_argument(
            "--superuser",
            action="store_true",   # flag booléen : présent = True, absent = False
            help="Crée un superuser (accès à l'admin Django) au lieu d'un user normal",
        )

    def handle(self, *args, **options):
        """
        Logique principale de la commande.
        `options` contient les arguments parsés — ici options["superuser"].
        """
        # get_user_model() retourne notre CustomUser — jamais importer User directement
        User = get_user_model()

        # Lecture depuis .env via python-decouple
        # Si la variable manque dans .env, decouple lève une UndefinedValueError claire
        email = config("SUPERUSER_EMAIL")
        password = config("SUPERUSER_PASSWORD")

        # Vérifie si l'utilisateur existe déjà — évite une erreur d'unicité sur l'email
        if User.objects.filter(email=email).exists():
            self.stdout.write(
                self.style.WARNING(f"⚠️  L'utilisateur {email} existe déjà — rien à faire.")
            )
            return

        if options["superuser"]:
            # create_superuser : is_staff=True + is_superuser=True + password hashé
            User.objects.create_superuser(email=email, password=password)
            self.stdout.write(
                self.style.SUCCESS(f"✅ Superuser créé : {email}")
            )
        else:
            # create_user : utilisateur normal, pas d'accès à l'admin Django
            User.objects.create_user(email=email, password=password)
            self.stdout.write(
                self.style.SUCCESS(f"✅ Utilisateur créé : {email}")
            )
