"""
accounts/management/commands/seed_accounts.py

Wizard interactif pour créer les comptes bancaires une fois pour toutes.

Usage :
    python manage.py seed_accounts

Le wizard pose les questions une à une :
    - IBAN (ou RIB pour CIC) — saisie masquée (getpass) pour ne pas afficher à l'écran
    - BIC — optionnel, pré-rempli depuis banks_config
    - Nom du compte — suggéré, modifiable

Idempotent : si un compte existe déjà (même contract_number), il est mis à jour.
Les données ne transitent jamais dans un fichier — saisie terminal uniquement.
"""

import getpass

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account, Bank, CheckingAccount, SavingsAccount


class Command(BaseCommand):
    help = (
        "Wizard interactif pour créer les comptes bancaires (IBAN/RIB saisi en direct)."
    )

    def handle(self, *args, **options):
        if not Bank.objects.filter(slug__in=["yuh", "ubs", "cic"]).exists():
            raise CommandError(
                "Banques introuvables. Lancez d'abord : python manage.py seed_banks"
            )

        self.stdout.write("\n╔══════════════════════════════════════════════════╗")
        self.stdout.write("║       BricBudget — Configuration des comptes     ║")
        self.stdout.write("╚══════════════════════════════════════════════════╝")
        self.stdout.write("\nLes valeurs saisies ne sont pas affichées à l'écran.")
        self.stdout.write("Laisser vide = passer / valeur entre [] = défaut.\n")

        created = 0
        updated = 0

        # ── Yuh ───────────────────────────────────────────────────────────────
        self.stdout.write("─" * 50)
        self.stdout.write("🏦  Yuh (CHF — compte courant)")
        self.stdout.write("    Pas d'identifiant dans le fichier CSV — IBAN saisi ici.")
        n_c, n_u = self._wizard_checking(
            bank_slug="yuh",
            default_name="Compte Yuh",
            contract_number="",
            iban_label="IBAN Yuh",
            iban_prefill="",
        )
        created += n_c
        updated += n_u

        # ── UBS ───────────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write("─" * 50)
        self.stdout.write("🏦  UBS (CHF — compte courant)")
        self.stdout.write("    L'IBAN est aussi extrait du fichier CSV à l'import.")
        n_c, n_u = self._wizard_checking(
            bank_slug="ubs",
            default_name="UBS Compte courant",
            contract_number=None,  # sera défini par l'IBAN saisi
            iban_label="IBAN UBS",
            iban_prefill="",
        )
        created += n_c
        updated += n_u

        # ── CIC ───────────────────────────────────────────────────────────────
        cic_accounts = [
            {
                "label": "CIC — Compte courant (EUR)",
                "type": Account.AccountType.CHECKING,
                "default_name": "Compte courant",
                "rib_label": "RIB Compte courant (sans espaces, visible dans Excel CIC)",
            },
            {
                "label": "CIC — Livret A (EUR)",
                "type": Account.AccountType.SAVINGS,
                "default_name": "Livret A",
                "rib_label": "RIB Livret A (sans espaces)",
            },
            {
                "label": "CIC — LDDS (EUR)",
                "type": Account.AccountType.SAVINGS,
                "default_name": "LDDS",
                "rib_label": "RIB LDDS (sans espaces)",
            },
        ]

        for acc in cic_accounts:
            self.stdout.write("")
            self.stdout.write("─" * 50)
            self.stdout.write(f"🏦  {acc['label']}")

            rib = self._prompt_secret(acc["rib_label"])
            if not rib:
                self.stdout.write(self.style.WARNING("    → Ignoré (RIB vide)."))
                continue

            rib = rib.replace(" ", "")  # normaliser sans espaces

            if acc["type"] == Account.AccountType.CHECKING:
                iban = self._prompt_secret(
                    "IBAN (optionnel — peut être ajouté plus tard)"
                )
                bic = self._prompt_secret(
                    "BIC (optionnel — peut être ajouté plus tard)"
                )
                name = self._prompt(
                    f"Nom du compte [{acc['default_name']}]",
                    default=acc["default_name"],
                )
                n_c, n_u = self._save_checking(
                    bank_slug="cic",
                    name=name,
                    currency=Account.Currency.EUR,
                    contract_number=rib,
                    iban=iban or None,
                    bic=bic,
                )
            else:
                name = self._prompt(
                    f"Nom du compte [{acc['default_name']}]",
                    default=acc["default_name"],
                )
                n_c, n_u = self._save_savings(
                    bank_slug="cic",
                    name=name,
                    currency=Account.Currency.EUR,
                    contract_number=rib,
                )
            created += n_c
            updated += n_u

        # ── Résumé ────────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write("═" * 50)
        self.stdout.write(
            self.style.SUCCESS(f"✓  {created} compte(s) créé(s), {updated} mis à jour.")
        )
        self._warn_incomplete()

    # ── Helpers prompt ────────────────────────────────────────────────────────

    def _prompt_secret(self, label):
        """Saisie masquée (ne s'affiche pas dans le terminal)."""
        return getpass.getpass(f"    {label} : ").strip()

    def _prompt(self, label, default=""):
        """Saisie normale avec valeur par défaut."""
        value = input(f"    {label} : ").strip()
        return value if value else default

    # ── Helpers save ──────────────────────────────────────────────────────────

    def _wizard_checking(
        self,
        bank_slug,
        default_name,
        contract_number,
        iban_label,
        iban_prefill,
    ):
        iban = self._prompt_secret(
            f"{iban_label} (optionnel — peut être ajouté plus tard)"
        )
        if not iban:
            iban = None
        else:
            iban = iban.replace(" ", "")

        bic = self._prompt_secret("BIC (optionnel — peut être ajouté plus tard)")
        name = self._prompt(f"Nom du compte [{default_name}]", default=default_name)

        # Pour UBS, le contract_number == IBAN
        if contract_number is None:
            contract_number = iban or ""

        return self._save_checking(
            bank_slug=bank_slug,
            name=name,
            currency=Account.Currency.CHF,
            contract_number=contract_number,
            iban=iban,
            bic=bic,
        )

    def _save_checking(self, bank_slug, name, currency, contract_number, iban, bic):
        bank = Bank.objects.get(slug=bank_slug)

        if contract_number:
            existing = Account.objects.filter(
                bank=bank, contract_number=contract_number
            ).first()
        else:
            existing = Account.objects.filter(
                bank=bank, account_type=Account.AccountType.CHECKING
            ).first()

        status = "" if (iban and bic) else "  ⚠ incomplet"

        if existing:
            existing.name = name
            existing.save()
            ca, _ = CheckingAccount.objects.get_or_create(account=existing)
            ca.iban = iban
            ca.bic = bic or ""
            ca.save()
            self.stdout.write(f"    · Mis à jour : {name}{status}")
            return 0, 1
        else:
            account = Account.objects.create(
                bank=bank,
                name=name,
                account_type=Account.AccountType.CHECKING,
                currency=currency,
                contract_number=contract_number,
                is_active=True,
            )
            CheckingAccount.objects.create(account=account, iban=iban, bic=bic or "")
            self.stdout.write(self.style.SUCCESS(f"    ✓ Créé : {name}{status}"))
            return 1, 0

    def _save_savings(self, bank_slug, name, currency, contract_number):
        bank = Bank.objects.get(slug=bank_slug)
        existing = Account.objects.filter(
            bank=bank, contract_number=contract_number
        ).first()

        if existing:
            existing.name = name
            existing.save()
            self.stdout.write(f"    · Mis à jour : {name}  ⚠ taux à définir")
            return 0, 1
        else:
            account = Account.objects.create(
                bank=bank,
                name=name,
                account_type=Account.AccountType.SAVINGS,
                currency=currency,
                contract_number=contract_number,
                is_active=True,
            )
            SavingsAccount.objects.create(account=account, interest_rate=0)
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ Créé : {name}  ⚠ taux à définir")
            )
            return 1, 0

    def _warn_incomplete(self):
        incomplete = []
        for ca in CheckingAccount.objects.select_related("account__bank"):
            if not ca.is_complete:
                missing = []
                if not ca.iban:
                    missing.append("IBAN")
                if not ca.bic:
                    missing.append("BIC")
                incomplete.append((ca.account, missing))
        for sa in SavingsAccount.objects.select_related("account__bank"):
            if not sa.is_complete:
                incomplete.append((sa.account, ["taux d'intérêt"]))

        if incomplete:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("⚠  Comptes incomplets (is_complete=False) :")
            )
            for account, missing in incomplete:
                self.stdout.write(
                    self.style.WARNING(
                        f"   • {account.bank.name} — {account.name} : {', '.join(missing)}"
                    )
                )
            self.stdout.write(
                self.style.WARNING(
                    "   → Compléter dans l'admin : http://localhost:8000/admin/accounts/checkingaccount/"
                )
            )
