# Generated manually — renames Profile fields to English equivalents.
#
# langue         → language
# devise_affichage → display_currency
#
# Also updates verbose_name / verbose_name_plural on CustomUser and Profile
# (metadata-only changes, no column rename in SQL).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        # RenameField generates: ALTER TABLE users_profile RENAME COLUMN langue TO language
        migrations.RenameField(
            model_name="profile",
            old_name="langue",
            new_name="language",
        ),
        # RenameField generates: ALTER TABLE users_profile RENAME COLUMN devise_affichage TO display_currency
        migrations.RenameField(
            model_name="profile",
            old_name="devise_affichage",
            new_name="display_currency",
        ),
        # AlterModelOptions only updates Django's internal state — no SQL generated.
        # Needed so that `makemigrations` doesn't detect a diff between the model
        # and the migration history on the next run.
        migrations.AlterModelOptions(
            name="customuser",
            options={"verbose_name": "user", "verbose_name_plural": "users"},
        ),
        migrations.AlterModelOptions(
            name="profile",
            options={"verbose_name": "profile", "verbose_name_plural": "profiles"},
        ),
    ]
