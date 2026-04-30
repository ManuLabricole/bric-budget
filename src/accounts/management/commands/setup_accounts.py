"""
accounts/management/commands/setup_accounts.py

Crée automatiquement les Banks + Accounts manquants à partir de fichiers d'export.

Usage :
    python manage.py setup_accounts --file export.csv --file releve_cic.xlsx

Logique :
    1. Pour chaque fichier → detect_connector() pour identifier la banque
    2. Crée la Bank en DB si elle n'existe pas (métadonnées hardcodées par connecteur)
    3. Extrait les identifiants de compte depuis le fichier
    4. Crée Account + CheckingAccount / SavingsAccount si ils n'existent pas déjà

Ce que la commande remplit automatiquement :
    - Bank : name, slug, icon_slug, default_currency
    - Account : bank, name, account_type, currency, contract_number
    - CheckingAccount : account (IBAN laissé vide — à compléter dans l'admin)
    - SavingsAccount : account (taux laissé à 0 — à compléter dans l'admin)

Ce que la commande NE remplit PAS (à compléter manuellement dans l'admin) :
    - CheckingAccount.iban  (CIC n'expose que le RIB, pas l'IBAN complet)
    - CheckingAccount.bic   (jamais dans les exports)
    - SavingsAccount.interest_rate  (jamais dans les exports)
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account, Bank, CheckingAccount, SavingsAccount
from connectors.cic.parser import CICConnector
from connectors.resolver import detect_connector
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector

# ── Métadonnées statiques par connecteur ──────────────────────────────────────
# Ces infos ne changent jamais — elles caractérisent la banque, pas le compte.
# icon_slug doit correspondre à un fichier dans static/icons/banks/miniature/.
BANK_DEFAULTS = {
    "yuh": {
        "name": "Yuh",
        "slug": "yuh",
        "icon_slug": "yuh",
        "default_currency": Account.Currency.CHF,
    },
    "ubs": {
        "name": "UBS",
        "slug": "ubs",
        "icon_slug": "ubs",
        "default_currency": Account.Currency.CHF,
    },
    "cic": {
        "name": "CIC",
        "slug": "cic",
        "icon_slug": "cic",
        "default_currency": Account.Currency.EUR,
    },
}

# Noms humains par défaut selon le nom de feuille CIC.
# Le fichier CIC utilise des noms de feuilles standardisés.
CIC_SHEET_ACCOUNT_TYPES = {
    "Compte courant": Account.AccountType.CHECKING,
    "Livret A": Account.AccountType.SAVINGS,
    "LDDS": Account.AccountType.SAVINGS,
    "LDD": Account.AccountType.SAVINGS,
}


class Command(BaseCommand):
    help = (
        "Crée les Banks et Accounts manquants à partir de fichiers d'export bancaire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            action="append",
            dest="files",
            metavar="PATH",
            required=True,
            help="Chemin vers un fichier d'export (répétable pour plusieurs fichiers).",
        )

    def handle(self, *args, **options):
        files = [Path(f) for f in options["files"]]

        for filepath in files:
            if not filepath.exists():
                raise CommandError(f"Fichier introuvable : {filepath}")

        self.stdout.write("")
        created_banks = 0
        created_accounts = 0

        for filepath in files:
            self.stdout.write(f"📂  {filepath.name}")

            connector = detect_connector(filepath)
            if connector is None:
                self.stdout.write(
                    self.style.WARNING("    ⚠  Format non reconnu — ignoré.\n")
                )
                continue

            # ── Créer (ou récupérer) la Bank ──────────────────────────────────
            bank_slug = self._bank_slug(connector)
            defaults = BANK_DEFAULTS[bank_slug]
            bank, bank_created = Bank.objects.get_or_create(
                slug=bank_slug,
                defaults={
                    "name": defaults["name"],
                    "icon_slug": defaults["icon_slug"],
                    "default_currency": defaults["default_currency"],
                },
            )
            if bank_created:
                created_banks += 1
                self.stdout.write(
                    self.style.SUCCESS(f"    ✓  Bank « {bank.name} » créée")
                )
            else:
                self.stdout.write(f"    ·  Bank « {bank.name} » déjà en DB")

            # ── Créer les comptes selon le connecteur ─────────────────────────
            n = self._create_accounts(connector, filepath, bank)
            created_accounts += n
            self.stdout.write("")

        # ── Résumé final ──────────────────────────────────────────────────────
        self.stdout.write("─" * 50)
        self.stdout.write(
            self.style.SUCCESS(
                f"✓  {created_banks} banque(s) et {created_accounts} compte(s) créé(s)."
            )
        )

        # Vérifier les comptes incomplets et avertir
        incomplete = self._find_incomplete_accounts()
        if incomplete:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("⚠  Comptes incomplets (à compléter dans l'admin) :")
            )
            for account, missing in incomplete:
                self.stdout.write(
                    self.style.WARNING(
                        f"   • {account.name} — manque : {', '.join(missing)}"
                    )
                )
            self.stdout.write(
                self.style.WARNING("   → http://localhost:8000/admin/accounts/account/")
            )
        self.stdout.write("")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _bank_slug(self, connector):
        if isinstance(connector, YuhConnector):
            return "yuh"
        if isinstance(connector, UBSConnector):
            return "ubs"
        if isinstance(connector, CICConnector):
            return "cic"
        raise CommandError(f"Connecteur non supporté : {type(connector).__name__}")

    def _create_accounts(self, connector, filepath, bank):
        """Crée les Account(s) pour ce fichier. Retourne le nombre créé."""
        created = 0

        if isinstance(connector, YuhConnector):
            created += self._create_single_account(
                bank=bank,
                name="Compte Yuh",
                account_type=Account.AccountType.CHECKING,
                currency=Account.Currency.CHF,
                contract_number="",
            )

        elif isinstance(connector, UBSConnector):
            identifier = connector.extract_account_identifier(filepath)
            if not identifier:
                self.stdout.write(
                    self.style.WARNING(
                        "    ⚠  Impossible d'extraire l'IBAN du fichier UBS."
                    )
                )
                return 0
            created += self._create_single_account(
                bank=bank,
                name=f"UBS {identifier[:12]}…",
                account_type=Account.AccountType.CHECKING,
                currency=Account.Currency.CHF,
                contract_number=identifier,
                iban=identifier,  # Pour UBS, contract_number == IBAN normalisé
            )

        elif isinstance(connector, CICConnector):
            sheets = connector.get_account_sheets(filepath)
            for sheet in sheets:
                account_type = CIC_SHEET_ACCOUNT_TYPES.get(
                    sheet["sheet_name"], Account.AccountType.CHECKING
                )
                created += self._create_single_account(
                    bank=bank,
                    name=sheet["sheet_name"],  # "Compte courant", "Livret A", "LDDS"
                    account_type=account_type,
                    currency=Account.Currency.EUR,
                    contract_number=sheet["rib"],
                )

        return created

    def _create_single_account(
        self, bank, name, account_type, currency, contract_number, iban=""
    ):
        """
        Crée un Account + sa spécialisation (CheckingAccount ou SavingsAccount).
        Retourne 1 si créé, 0 si déjà existant.

        On cherche le compte par (bank + contract_number) si contract_number est
        renseigné, sinon par (bank + account_type) — cas Yuh (1 seul compte).
        """
        if contract_number:
            existing = Account.objects.filter(
                bank=bank, contract_number=contract_number
            ).first()
        else:
            existing = Account.objects.filter(
                bank=bank, account_type=account_type
            ).first()

        if existing:
            self.stdout.write(f"    ·  Compte « {existing.name} » déjà en DB")
            return 0

        # Créer l'Account de base
        account = Account.objects.create(
            bank=bank,
            name=name,
            account_type=account_type,
            currency=currency,
            contract_number=contract_number,
            is_active=True,
        )

        # Créer la spécialisation selon le type
        if account_type == Account.AccountType.CHECKING:
            CheckingAccount.objects.create(account=account, iban=iban, bic="")
            missing = []
            if not iban:
                missing.append("IBAN")
            missing.append("BIC")
            status = f"(manque : {', '.join(missing)})" if missing else ""
        else:
            SavingsAccount.objects.create(account=account, interest_rate=0)
            status = "(taux à 0% — à compléter)"

        self.stdout.write(
            self.style.SUCCESS(f"    ✓  Compte « {name} » créé  {status}")
        )
        return 1

    def _find_incomplete_accounts(self):
        """Retourne les comptes dont les infos essentielles sont manquantes."""
        incomplete = []

        for ca in CheckingAccount.objects.select_related("account"):
            missing = []
            if not ca.iban:
                missing.append("IBAN")
            if not ca.bic:
                missing.append("BIC")
            if missing:
                incomplete.append((ca.account, missing))

        for sa in SavingsAccount.objects.select_related("account"):
            if not sa.is_complete:
                incomplete.append((sa.account, ["taux d'intérêt"]))

        return incomplete
