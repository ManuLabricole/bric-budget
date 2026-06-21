"""accounts/models/account.py — Account (enveloppe générique) + AccountQuerySet."""

from django.conf import settings
from django.db import models

from .institution import Institution

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
        CHECKING = "checking", "Checking account"
        SAVINGS = "savings", "Savings account"
        PENSION_3A = "pension_3a", "3rd pillar (3a)"
        PENSION_LP = "pension_lp", "Vested benefits (LP)"
        INVESTMENT = "investment", "Investment account / Titres"
        CARD = "card", "Credit / Debit card"
        INSURANCE = "insurance", "Life insurance / Assurance vie"
        BROKERAGE = "brokerage", "Brokerage / Compte titres"
        # Phase 3A — exchange crypto (Binance, Kraken…).
        # provider = account.institution, wallet = external_ref (Phase 3A-bis).
        CRYPTO = "crypto", "Crypto exchange"

    # Types dont la devise est contrainte (SR imposé par réglementation).
    _CHF_ONLY_TYPES = {"pension_3a", "pension_lp"}

    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,  # PROTECT: prevents deleting an institution that has accounts
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
    #   En stockant l'IBAN ici, le resolver peut faire Account.objects.get(iban=..., institution__slug="ubs")
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

    # Phase 3A — date d'ouverture / clôture.
    # opened_at sert au calcul d'antériorité fiscale (AV 8 ans, PEA 5 ans...).
    opened_at = models.DateField(null=True, blank=True)
    closed_at = models.DateField(null=True, blank=True)

    # Juridiction fiscale de l'enveloppe — CH / FR (défaut = institution.country).
    # Distinct de institution.country : un résident FR peut avoir un compte CH
    # soumis au droit français (compte joint transfrontalier, etc.).
    fiscal_country = models.CharField(max_length=2, blank=True, default="")

    # Couleur stable d'affichage dans les charts patrimoine (#134). Allouée à la
    # création via services.colors.allocate_color() (domaine = comptes du user) puis
    # FIGÉE → le compte garde sa teinte même quand d'autres comptes arrivent. Pattern
    # calqué sur Category.colour_hex. blank = comptes créés avant la feature (backfillés
    # par la data-migration 0020) ou créés hors create_account (filet : _STACK_PALETTE).
    colour_hex = models.CharField(max_length=7, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    # Manager custom — expose Account.objects.for_user(user).
    # Même pattern que Transaction.objects.for_user(user).
    objects = AccountQuerySet.as_manager()

    class Meta:
        verbose_name = "account"
        verbose_name_plural = "accounts"
        ordering = ["institution__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.currency}) — {self.institution.name}"

    def save(self, *args, **kwargs):
        # Hériter le pays de l'institution si non renseigné.
        if not self.fiscal_country and self.institution_id:
            self.fiscal_country = self.institution.country
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.account_type in self._CHF_ONLY_TYPES and self.currency != "CHF":
            raise ValidationError(
                {
                    "currency": f"Les comptes de type « {self.get_account_type_display()} » "
                    "sont obligatoirement en CHF (réglementation suisse)."
                }
            )

    @property
    def iban_display(self):
        """IBAN masqué : CH56 **** **** **** **** *  (4 premiers + 3 derniers visibles)."""
        if not self.iban:
            return None
        return self.iban[:4] + " **** **** **** **** " + self.iban[-3:]
