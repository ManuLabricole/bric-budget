"""
accounts/models.py — Infrastructure bancaire de BricBudget

Ordre des modèles = ordre des dépendances FK :
    Bank → Account → CompteCourant (spécialisation Phase 0A)
                   → AccountAccess (User ↔ Account)
                   → Card
                   → BalanceSnapshot
    ExchangeRate (indépendant)
"""

from django.db import models


# =============================================================================
# Bank — La banque
# =============================================================================

class Bank(models.Model):
    """
    Une institution bancaire : Yuh, CIC, UBS, Monzo...

    slug : identifiant URL-friendly généré depuis le nom.
    Exemple : "Yuh" → "yuh", "CIC France" → "cic-france".
    Utile pour les URLs et les imports (identifier la banque sans l'id).

    devise_principale : la devise native de la banque.
    Yuh → CHF, CIC → EUR, Monzo → GBP.
    Sert de valeur par défaut pour les nouveaux comptes créés dans cette banque.
    """

    name = models.CharField(max_length=100, unique=True, verbose_name="nom")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="slug")

    # Code pays ISO 3166-1 alpha-2 : CH, FR, GB...
    country = models.CharField(max_length=2, verbose_name="pays (code ISO)")

    # Code devise ISO 4217 : CHF, EUR, GBP...
    default_currency = models.CharField(
        max_length=3,
        verbose_name="devise principale",
    )

    is_active = models.BooleanField(default=True, verbose_name="active")

    class Meta:
        verbose_name = "banque"
        verbose_name_plural = "banques"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.country})"


# =============================================================================
# Account — Le compte bancaire (table générique de base)
# =============================================================================

class Account(models.Model):
    """
    Table générique représentant n'importe quel compte bancaire.

    Pourquoi "générique" ?
    ----------------------
    Un compte courant Yuh et un 3ème pilier Finpension ont des champs communs
    (banque, nom, devise, actif) mais aussi des champs très différents.
    On met les champs communs ici, et les champs spécifiques dans des tables
    dédiées : CompteCourant, CompteEpargne, ComptePrevoyance... (Phase 4+)

    Le champ `account_type` est un discriminateur : il dit quelle table
    spécialisée contient les détails de ce compte.
    Exemple : account_type="current" → chercher CompteCourant(account=this)
    """

    class AccountType(models.TextChoices):
        # Phase 0A — implémentés maintenant
        CURRENT     = "current",    "Compte courant"
        # Phase 4 — tables spécialisées à créer plus tard
        SAVINGS     = "savings",    "Compte épargne"
        PENSION_3A  = "pension_3a", "3ème pilier (3a)"
        PENSION_LP  = "pension_lp", "Libre passage (LP)"
        # Phase 5
        INVESTMENT  = "investment", "Compte investissement"

    bank = models.ForeignKey(
        Bank,
        on_delete=models.PROTECT,   # PROTECT : interdit de supprimer une banque qui a des comptes
        related_name="accounts",
        verbose_name="banque",
    )

    name = models.CharField(max_length=200, verbose_name="nom")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="slug")

    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        verbose_name="type de compte",
    )

    # Code devise ISO 4217 : CHF, EUR, GBP...
    currency = models.CharField(max_length=3, verbose_name="devise")

    is_active = models.BooleanField(default=True, verbose_name="actif")

    created_at = models.DateTimeField(auto_now_add=True)  # rempli automatiquement à la création

    class Meta:
        verbose_name = "compte"
        verbose_name_plural = "comptes"
        ordering = ["bank__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.currency}) — {self.bank.name}"


# =============================================================================
# CompteCourant — Spécialisation d'Account pour les comptes courants
# =============================================================================

class CompteCourant(models.Model):
    """
    Champs spécifiques aux comptes courants (Yuh CHF, CIC C/C...).

    Pourquoi OneToOne et pas hériter directement d'Account ?
    --------------------------------------------------------
    Django propose l'héritage de modèles, mais il crée des jointures SQL
    automatiques qui peuvent être lentes et difficiles à débugger.
    OneToOne explicite = on contrôle exactement la jointure, c'est transparent.

    Depuis le code on accèdra ainsi :
        account.comptecourant.iban   ← depuis un Account
        cc.account.name              ← depuis un CompteCourant

    Phase 4+ : on créera CompteEpargne, ComptePrevoyance3a, etc.
    sur le même principe — chacun avec ses propres champs métier.
    """

    # primary_key=True : pas d'id séparé — l'id de CompteCourant = l'id de Account
    # Évite une colonne inutile et rend la relation encore plus explicite
    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,   # CASCADE : si Account supprimé, CompteCourant aussi
        primary_key=True,
        related_name="comptecourant",
        verbose_name="compte",
    )

    # IBAN : International Bank Account Number — ex: CH56 0483 5012 3456 7800 9
    # blank=True + default="" : champ optionnel (Finpension n'en a pas toujours)
    iban = models.CharField(
        max_length=34,
        blank=True,
        default="",
        verbose_name="IBAN",
    )

    # BIC/SWIFT : identifiant de la banque dans les virements internationaux
    # ex: YUHHCHZZ pour Yuh
    bic = models.CharField(
        max_length=11,
        blank=True,
        default="",
        verbose_name="BIC / SWIFT",
    )

    class Meta:
        verbose_name = "compte courant"
        verbose_name_plural = "comptes courants"

    def __str__(self):
        return f"CompteCourant — {self.account.name}"


# =============================================================================
# BalanceSnapshot — Solde d'un compte à un instant T
# =============================================================================

class BalanceSnapshot(models.Model):
    """
    Capture du solde d'un compte à une date donnée.

    Créé automatiquement à chaque import de fichier.
    Pour Yuh : le solde est extrait du nom de fichier CSV.
    Exemple : "Activités_2026_03_17 - 33,344.CSV" → 33 344 CHF le 2026-03-17

    solde_chf : le solde converti en CHF (devise de référence).
    Utile pour consolider le patrimoine net multi-devises sur les graphiques.
    Pour un compte déjà en CHF, solde_chf = solde.
    """

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="balance_snapshots",
        verbose_name="compte",
    )

    date = models.DateField(verbose_name="date du snapshot")

    # max_digits=14 : supporte jusqu'à 999 milliards — largement suffisant
    # decimal_places=2 : précision au centime
    solde = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="solde",
    )

    # La devise du solde brut — peut différer de account.currency (rare mais possible)
    currency = models.CharField(max_length=3, verbose_name="devise")

    # Solde converti en CHF via ExchangeRate — pour les graphiques consolidés
    # null=True : pas encore converti si le taux du jour n'est pas encore chargé
    solde_chf = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="solde en CHF",
    )

    class Source(models.TextChoices):
        IMPORT = "import", "Import fichier"
        MANUAL = "manual", "Saisie manuelle"

    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.IMPORT,
        verbose_name="source",
    )

    class Meta:
        verbose_name = "snapshot de solde"
        verbose_name_plural = "snapshots de solde"
        ordering = ["-date"]
        # Un seul snapshot par compte par date
        unique_together = [("account", "date")]

    def __str__(self):
        return f"{self.account.name} — {self.date} : {self.solde} {self.currency}"
