import logging
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.shortcuts import redirect, render

from accounts.models import Account, Bank, CheckingAccount, SavingsAccount

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

CURRENCIES = ["CHF", "EUR", "GBP", "USD"]


@login_required
def account_new(request: "HttpRequest") -> "HttpResponse":
    banks = Bank.objects.all().order_by("name")
    account_types = Account.AccountType.choices

    if request.method == "POST":
        bank_slug = request.POST.get("bank_slug", "")
        account_name = request.POST.get("account_name", "").strip()
        account_type = request.POST.get("account_type", "")
        iban = request.POST.get("iban", "").replace(" ", "").upper()
        bic = request.POST.get("bic", "").replace(" ", "").upper()
        currency = request.POST.get("currency", "CHF")

        errors: list[str] = []
        if not account_name:
            errors.append("Le nom du compte est obligatoire.")
        if not iban:
            errors.append("L'IBAN est obligatoire.")
        if account_type not in dict(Account.AccountType.choices):
            errors.append("Type de compte invalide.")

        bank = None
        try:
            bank = Bank.objects.get(slug=bank_slug)
        except Bank.DoesNotExist:
            errors.append(f"Banque introuvable : {bank_slug}.")

        if errors:
            return render(
                request,
                "accounts/account_new.html",
                {
                    "banks": banks,
                    "account_types": account_types,
                    "currencies": CURRENCIES,
                    "errors": errors,
                    "form_data": request.POST,
                },
            )

        with db_transaction.atomic():
            account = Account.objects.create(
                bank=bank,  # type: ignore[misc]  # bank is guaranteed non-None (errors guard above)
                name=account_name,
                account_type=account_type,
                currency=currency,
                is_active=True,
            )
            account.members.add(request.user)  # type: ignore[arg-type]  # login_required ensures CustomUser
            if account_type == Account.AccountType.CHECKING.value:
                CheckingAccount.objects.create(account=account, iban=iban, bic=bic)
            else:
                SavingsAccount.objects.create(account=account, interest_rate=0)

        logger.info(
            "account_new: id=%s bank=%s type=%s user=%s",
            account.id,
            bank_slug,
            account_type,
            request.user.id,
        )
        return redirect("imports:upload")

    return render(
        request,
        "accounts/account_new.html",
        {
            "banks": banks,
            "account_types": account_types,
            "currencies": CURRENCIES,
        },
    )
