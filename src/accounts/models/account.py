"""accounts/models/account.py — Account (enveloppe générique) + AccountQuerySet."""

from django.conf import settings
from django.db import models

from .bank import Bank

# =============================================================================
# AccountQuerySet — Queryset manager avec filtre de sécurité par user
# =============================================================================


class AccountQuerySet(models.QuerySet):
    """
    QuerySet custom pour Account.

    Méthode principale : .for_user(user)
        Filtre les comptes selon les membres — même pattern que
        TransactionQuerySet.for_user(user).

        À appeler partout où les vues ou le resolver exposent des comptes :

            Account.objects.for_user(request.user).filter(is_active=True)

        Pourquoi un QuerySet et pas un filtre inline ?
            - DRY : si Account.members change de nom ou de structure, un seul
              endroit à mettre à jour.
            - Chainable : retourne un QuerySet standard.
            - Cohérence : même contrat que Transaction.objects.for_user().
    """

    def for_user(self, user):
        """
        Retourne uniquement les comptes dont `user` est membre.

        Un user non-membre d'aucun compte obtient un queryset vide.
        Passer None retourne tous les comptes (usage CLI uniquement).
        """
        if user is None:
            return self
        return self.filter(members=user)


# =============================================================================
# Account — Generic bank account (base table)
# =============================================================================


class Account(models.Model):
    """
    Generic model representing any bank account.

    Why "generic"?
    --------------
    A Yuh checking account and a Finpension 3rd-pillar account share common
    fields (bank, name, currency, active) but also have very different ones.
    Common fields live here; type-specific fields live in dedicated tables:
    CheckingAccount, SavingsAccount, PensionAccount... (Phase 4+)

    The `account_type` field is a discriminator: it tells which specialised
    table holds the details for this account.
    Example: account_type="checking" → look up CheckingAccount(account=this)
    """

    class Currency(models.TextChoices):
        CHF = "CHF", "CHF — Franc suisse"
        EUR = "EUR", "EUR — Euro"
        GBP = "GBP", "GBP — Livre sterling"
        USD = "USD", "USD — Dollar américain"

    class AccountType(models.TextChoices):
        # Phase 0A — implemented now
        CHECKING = "checking", "Checking account"
        # Phase 2G — already exists as SavingsAccount specialisation
        SAVINGS = "savings", "Savings account"
        # Phase 4 — pension accounts (Finpension 3a + LP)
        PENSION_3A = "pension_3a", "3rd pillar (3a)"
        PENSION_LP = "pension_lp", "Vested benefits (LP)"
        # Phase 5 — investment & trading (titres, ETF...)
        INVESTMENT = "investment", "Investment account / Titres"
        # Phase 6 — payment cards (debit + credit)
        # Import: matched by Card.last_four extracted from statement
        CARD = "card", "Credit / Debit card"
        # Phase 7 — insurance & assurance vie
        # Import: PDF relevé de valeur ou CSV de rachat. Identifier = policy number.
        # Pas de transactions au sens bancaire — on enregistre des snapshots de valeur.
        # Le connecteur lira le numéro de police depuis le relevé pour le matching.
        INSURANCE = "insurance", "Life insurance / Assurance vie"
        # Phase 7 — standalone brokerage (Swissquote, Degiro, IBKR...)
        # Import: CSV relevé mensuel. Transactions = achats/ventes de titres.
        # Matching par numéro de compte courtier (ex: "SQ-XXXXXXXX").
        BROKERAGE = "brokerage", "Brokerage / Compte titres"

    bank = models.ForeignKey(
        Bank,
        on_delete=models.PROTECT,  # PROTECT: prevents deleting a bank that has accounts
        related_name="accounts",
    )

    name = models.CharField(max_length=200)

    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
    )

    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.CHF,
    )

    # Bank-assigned contract number — used by import connectors to match a file to an account.
    # Each bank uses its own format:
    #   CIC : "10096XXXXXXXXXXXXXXXXXXX" (RIB without spaces)
    #   Yuh : not needed (single active account matched by bank slug)
    # blank=True: optional — not all banks expose a contract number in their exports.
    contract_number = models.CharField(max_length=100, blank=True, default="")

    # IBAN universel au niveau Account — identifiant de résolution pour tous les types de comptes.
    # Pourquoi ici et pas dans CheckingAccount seulement ?
    #   UBS exporte des relevés d'épargne (SavingsAccount) qui contiennent un IBAN en ligne 2.
    #   En stockant l'IBAN ici, le resolver peut faire Account.objects.get(iban=..., bank__slug="ubs")
    #   sans connaître le sous-type — propre pour les futures cartes, assurances, etc.
    # CheckingAccount.iban reste pour la rétrocompatibilité et l'affichage de iban_display.
    # NULL != NULL en SQL → unique=True avec null=True autorise plusieurs comptes sans IBAN.
    iban = models.CharField(
        max_length=34,
        unique=True,
        null=True,
        blank=True,
        default=None,
    )

    is_active = models.BooleanField(default=True)

    # Membres ayant accès à ce compte.
    # M2M → supporte les comptes joints (Emmanuel + Carys sur le même compte).
    # blank=True → pas de contrainte form-level ; la validation métier est dans les vues.
    # Toutes les requêtes Transaction filtrent par account__members=request.user
    # pour garantir qu'un user ne voit jamais les données d'un compte dont il n'est pas membre.
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="accounts",
        blank=True,
        verbose_name="Membres ayant accès",
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )  # set automatically on creation

    # Manager custom — expose Account.objects.for_user(user).
    # Même pattern que Transaction.objects.for_user(user).
    objects = AccountQuerySet.as_manager()

    class Meta:
        verbose_name = "account"
        verbose_name_plural = "accounts"
        ordering = ["bank__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.currency}) — {self.bank.name}"

    @property
    def iban_display(self):
        """IBAN masqué : CH56 **** **** **** **** *  (4 premiers + 3 derniers visibles)."""
        if not self.iban:
            return None
        return self.iban[:4] + " **** **** **** **** " + self.iban[-3:]
