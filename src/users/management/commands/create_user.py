"""
users/management/commands/create_user.py

Custom Django management command: creates a user from .env variables.

Why a custom command?
----------------------
`manage.py createsuperuser` is interactive — it asks questions every time.
Unusable in a script or after a DB reset.
This command reads credentials from .env and creates the user in one line.

Usage:
    python manage.py create_user                   # creates a regular user
    python manage.py create_user --superuser       # creates a superuser

Required .env variables:
    SUPERUSER_EMAIL=your@email.com
    SUPERUSER_PASSWORD=your_password

Django pattern — every custom command inherits from BaseCommand and implements:
    - add_arguments(): declares CLI arguments (optional)
    - handle():        the code that runs when the command is invoked
"""

from decouple import config
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    # Description shown by `python manage.py help create_user`
    help = "Creates a user (or superuser) from environment variables in .env"

    def add_arguments(self, parser):
        """
        Declares optional command arguments.
        `parser` is a standard Python ArgumentParser.
        """
        parser.add_argument(
            "--superuser",
            action="store_true",  # boolean flag: present = True, absent = False
            help="Creates a superuser (Django admin access) instead of a regular user",
        )

    def handle(self, *args, **options):
        """
        Main command logic.
        `options` contains the parsed arguments — here options["superuser"].
        """
        # get_user_model() returns our CustomUser — never import User directly
        User = get_user_model()

        # Read from .env via python-decouple
        # If a variable is missing from .env, decouple raises a clear UndefinedValueError
        email = config("SUPERUSER_EMAIL")
        password = config("SUPERUSER_PASSWORD")

        # Check if the user already exists — avoids a unique constraint error on email
        if User.objects.filter(email=email).exists():
            self.stdout.write(
                self.style.WARNING(f"User {email} already exists — nothing to do.")
            )
            return

        if options["superuser"]:
            # create_superuser: is_staff=True + is_superuser=True + hashed password
            User.objects.create_superuser(email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Superuser created: {email}"))
        else:
            # create_user: regular user, no Django admin access
            User.objects.create_user(email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"User created: {email}"))
