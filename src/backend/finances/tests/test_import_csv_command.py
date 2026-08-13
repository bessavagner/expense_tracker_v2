from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from model_bakery import baker

from accounts.resolution import household_for_user
from finances.models import (
    Category,
    Entry,
    EntryType,
    Income,
    InstallmentPlan,
    PaymentMethod,
    PaymentMethodClosingDay,
    SystemicExpense,
)


def write(dirpath, name, content):
    (dirpath / name).write_text(content, encoding="utf-8")


@pytest.fixture
def importdir(tmp_path):
    return tmp_path


@pytest.mark.django_db
class TestImportPaymentMethods:
    def test_creates_payment_methods_with_types_and_overrides(self, user, importdir):
        write(
            importdir,
            "formas_pagamento.csv",
            "nome,out./2025,nov./2025,jan./2026\n"
            "Dinheiro,-1,-1,-1\n"
            "Pix,-1,-1,-1\n"
            "Crédito C6,25,24,23\n",
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))

        cash = PaymentMethod.objects.get(user=user, name="Dinheiro")
        assert cash.type == "cash"
        assert cash.closing_day is None

        pix = PaymentMethod.objects.get(user=user, name="Pix")
        assert pix.type == "pix"

        c6 = PaymentMethod.objects.get(user=user, name="Crédito C6")
        assert c6.type == "credit_card"
        # default closing day = most frequent value
        assert c6.closing_day == 25
        # per-month overrides recorded where they differ from default
        assert (
            PaymentMethodClosingDay.objects.get(
                payment_method=c6, month=date(2025, 11, 1)
            ).closing_day
            == 24
        )
        assert (
            PaymentMethodClosingDay.objects.get(
                payment_method=c6, month=date(2026, 1, 1)
            ).closing_day
            == 23
        )

    def test_idempotent(self, user, importdir):
        write(importdir, "formas_pagamento.csv", "nome,out./2025\nPix,-1\n")
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        assert PaymentMethod.objects.filter(user=user, name="Pix").count() == 1


@pytest.mark.django_db
class TestImportIncome:
    def test_unpivots_income_per_month(self, user, importdir):
        write(
            importdir,
            "renda.csv",
            'nome,nov./2025,dez./2025\nSalário,"R$ 5.815,91",\n13°,,"R$ 3.998,74"\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))

        salario = Income.objects.get(user=user, name="Salário", month=date(2025, 11, 1))
        assert salario.amount == Decimal("5815.91")
        assert not Income.objects.filter(name="Salário", month=date(2025, 12, 1)).exists()
        assert Income.objects.get(user=user, name="13°", month=date(2025, 12, 1)).amount == Decimal(
            "3998.74"
        )

    def test_idempotent(self, user, importdir):
        write(importdir, "renda.csv", 'nome,nov./2025\nSalário,"R$ 5.000,00"\n')
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        assert Income.objects.filter(user=user, name="Salário").count() == 1


@pytest.mark.django_db
class TestImportSystemics:
    def test_creates_template_and_monthly_entries_via_pix(self, user, importdir):
        write(
            importdir,
            "sistemicas.csv",
            'nome,categoria,nov./2025,dez./2025\nEnel,Custeio,"R$ 460,00","R$ 579,25"\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))

        se = SystemicExpense.objects.get(user=user, name="Enel")
        assert se.category.name == "Custeio"  # auto-created
        assert se.payment_method.type == "pix"

        entries = (
            Entry.objects.for_household(household_for_user(user))
            .filter(systemic_expense=se)
            .order_by("date")
        )
        assert entries.count() == 2
        nov = entries.get(date=date(2025, 11, 1))
        assert nov.amount == Decimal("460.00")
        assert nov.entry_type == EntryType.SYSTEMIC
        assert nov.payment_method.type == "pix"
        assert nov.billing_month == date(2025, 11, 1)

    def test_idempotent(self, user, importdir):
        write(importdir, "sistemicas.csv", 'nome,categoria,nov./2025\nEnel,Custeio,"R$ 460,00"\n')
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        assert SystemicExpense.objects.filter(user=user, name="Enel").count() == 1
        assert (
            Entry.objects.for_household(household_for_user(user))
            .filter(entry_type=EntryType.SYSTEMIC)
            .count()
            == 1
        )


@pytest.mark.django_db
class TestImportRegularEntries:
    def test_imports_monthly_file_as_regular_entries(self, user, importdir):
        write(importdir, "formas_pagamento.csv", "nome,out./2025\nPix,-1\n")
        write(
            importdir,
            "outubro_2025.csv",
            'data,valor,descrição,categoria,forma\n03/10/2025,"R$ 32,91",Zé Delivery,Álcool,Pix\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))

        entry = Entry.objects.get(user=user, description="Zé Delivery")
        assert entry.amount == Decimal("32.91")
        assert entry.date == date(2025, 10, 3)
        assert entry.category.name == "Álcool"  # auto-created
        assert entry.payment_method.name == "Pix"
        assert entry.entry_type == EntryType.REGULAR

    def test_idempotent(self, user, importdir):
        write(importdir, "formas_pagamento.csv", "nome,out./2025\nPix,-1\n")
        write(
            importdir,
            "outubro_2025.csv",
            'data,valor,descrição,categoria,forma\n03/10/2025,"R$ 32,91",Zé,Álcool,Pix\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        assert Entry.objects.filter(user=user, description="Zé").count() == 1


@pytest.mark.django_db
class TestImportInstallments:
    def test_creates_plan_and_generates_entries(self, user, importdir):
        write(importdir, "formas_pagamento.csv", "nome,out./2025\nCrédito C6,25\n")
        write(
            importdir,
            "parcelamentos.csv",
            "data,valor,descrição,categoria,forma,parcelas,valor_parcela\n"
            '01/11/2025,"R$ 193,19",Camisetas,Roupa,Crédito C6,2,"R$ 96,60"\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))

        plan = InstallmentPlan.objects.get(user=user, description="Camisetas")
        assert plan.num_installments == 2
        assert plan.total_amount == Decimal("193.19")
        entries = Entry.objects.filter(user=user, installment_plan=plan)
        assert entries.count() == 2
        assert all(e.entry_type == EntryType.INSTALLMENT for e in entries)

    def test_idempotent(self, user, importdir):
        write(importdir, "formas_pagamento.csv", "nome,out./2025\nCrédito C6,25\n")
        write(
            importdir,
            "parcelamentos.csv",
            "data,valor,descrição,categoria,forma,parcelas,valor_parcela\n"
            '01/11/2025,"R$ 193,19",Camisetas,Roupa,Crédito C6,2,"R$ 96,60"\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        assert InstallmentPlan.objects.filter(user=user, description="Camisetas").count() == 1
        assert Entry.objects.filter(user=user, entry_type=EntryType.INSTALLMENT).count() == 2


@pytest.mark.django_db
class TestImportErrors:
    def test_unknown_user_raises(self, importdir):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("import_csv", "--user", "ghost", "--dir", str(importdir))


@pytest.mark.django_db
class TestDedupBreadth:
    def test_same_day_amount_description_on_different_methods_both_import(self, user, importdir):
        write(importdir, "formas_pagamento.csv", "nome,out./2025\nPix,-1\nDinheiro,-1\n")
        write(
            importdir,
            "outubro_2025.csv",
            "data,valor,descrição,categoria,forma\n"
            '03/10/2025,"R$ 10,00",Café,Lanche,Pix\n'
            '03/10/2025,"R$ 10,00",Café,Lanche,Dinheiro\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        assert Entry.objects.filter(user=user, description="Café").count() == 2

    def test_same_plan_on_different_methods_both_import(self, user, importdir):
        write(
            importdir,
            "formas_pagamento.csv",
            "nome,out./2025\nCrédito C6,25\nCrédito Nubank,30\n",
        )
        write(
            importdir,
            "parcelamentos.csv",
            "data,valor,descrição,categoria,forma,parcelas,valor_parcela\n"
            '01/11/2025,"R$ 100,00",Tênis,Roupa,Crédito C6,2,"R$ 50,00"\n'
            '01/11/2025,"R$ 100,00",Tênis,Roupa,Crédito Nubank,2,"R$ 50,00"\n',
        )
        call_command("import_csv", "--user", user.username, "--dir", str(importdir))
        assert InstallmentPlan.objects.filter(user=user, description="Tênis").count() == 2


@pytest.mark.django_db
class TestHouseholdScoping:
    """The command resolves the household once from the CLI username; every row
    it writes must land there, authored by that user."""

    def _seed_csv(self, importdir):
        write(importdir, "formas_pagamento.csv", "nome,out./2025\nPix,-1\n")
        write(
            importdir,
            "outubro_2025.csv",
            "data,valor,descrição,categoria,forma\n"
            '03/10/2025,"R$ 32,91",Zé Delivery,Alimentação,Pix\n',
        )

    def test_import_csv_writes_into_the_users_household(self, user, household, importdir):
        self._seed_csv(importdir)

        call_command("import_csv", "--user", user.username, "--dir", str(importdir))

        entry = Entry.objects.get(description="Zé Delivery")
        assert entry.household == household
        assert entry.created_by == user
        assert entry.user == user  # still NOT NULL until phase 4
        assert entry.category.household == household
        assert entry.payment_method.household == household

    def test_import_csv_ignores_another_households_catalogue(
        self, user, household, other_user, other_household, importdir
    ):
        """A same-named category in the neighbour's ledger must not be reused —
        the import would otherwise attach this household's rows to their row."""
        theirs = baker.make(
            "finances.Category",
            user=other_user,
            household=other_household,
            name="Alimentação",
        )
        self._seed_csv(importdir)

        call_command("import_csv", "--user", user.username, "--dir", str(importdir))

        mine = Category.objects.for_household(household).get(name="Alimentação")
        assert mine.pk != theirs.pk
        assert Entry.objects.get(description="Zé Delivery").category == mine

    def test_a_second_member_reuses_the_households_catalogue(
        self, user, household, other_user, importdir
    ):
        """The behavioural change this task makes. `other_user` joins the same
        household; importing as them must reuse the household's category, not
        mint a private duplicate — the whole point of a shared ledger."""
        from accounts.models import Membership, Role

        mine = baker.make("finances.Category", user=user, household=household, name="Alimentação")
        baker.make(Membership, user=other_user, household=household, role=Role.MEMBER)
        self._seed_csv(importdir)

        call_command("import_csv", "--user", other_user.username, "--dir", str(importdir))

        assert Category.objects.for_household(household).filter(name="Alimentação").count() == 1
        assert Entry.objects.get(description="Zé Delivery").category == mine
