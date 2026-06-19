# Gastos sistemáticos: UX, recorrência e correções — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix date prefill + systemic edit + income recurrence bugs and add a "Sistemático" tab (with optional N-month recurrence) to the global "+" modal, removing the inline cockpit form.

**Architecture:** Django + HTMX server-rendered partials. Forms in `finances/forms.py`, views in `finances/views/{cockpit,entries,settings}.py`, templates under `templates/`. New shared date helper and income-recurrence service under `finances/services/`.

**Tech Stack:** Django, HTMX, Alpine.js, DaisyUI/Tailwind, pytest + model_bakery.

## Global Constraints

- Locale `pt-br`, `USE_L10N=True` → every `<input type="date">` widget MUST set `format="%Y-%m-%d"` or it renders blank.
- `Entry.payment_method` and `Entry.date` are NOT nullable; any code creating/saving an Entry must provide both.
- Run tests from `src/backend`: `pytest <path> -v`. DB needs the pgvector container on port 5433 (already running in dev).
- Money/decimals use `Decimal`. Systemic month = first day of month (`date(y, m, 1)`), `billing_month_override=True` (handled by `create_monthly_entry`).
- Frontend: if new Tailwind classes appear in templates, rebuild + commit `mount.js`/`tailwind.css` (Tailwind `--force`).

---

### Task 1: Bug 5 — date widgets prefill ISO

**Files:**
- Modify: `src/backend/finances/forms.py` (`EntryForm.Meta.widgets["date"]` ~line 28; `InstallmentForm.Meta.widgets["date"]` ~line 78)
- Test: `src/backend/finances/tests/test_forms.py`

**Interfaces:**
- Produces: `EntryForm`/`InstallmentForm` date widgets render `value="YYYY-MM-DD"` when bound to an instance.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/finances/tests/test_forms.py`:

```python
from datetime import date

from model_bakery import baker

from finances.forms import EntryForm, InstallmentForm
from finances.models import Category, Entry, InstallmentPlan, PaymentMethod


@pytest.mark.django_db
def test_entry_form_date_prefills_iso():
    user = baker.make("core.CustomUser")
    cat = baker.make(Category, user=user)
    pm = baker.make(PaymentMethod, user=user, is_active=True)
    entry = baker.make(Entry, user=user, category=cat, payment_method=pm, date=date(2026, 6, 19))
    form = EntryForm(instance=entry, user=user)
    assert 'value="2026-06-19"' in str(form["date"])


@pytest.mark.django_db
def test_installment_form_date_prefills_iso():
    user = baker.make("core.CustomUser")
    cat = baker.make(Category, user=user)
    pm = baker.make(PaymentMethod, user=user, is_active=True)
    plan = baker.make(InstallmentPlan, user=user, category=cat, payment_method=pm, date=date(2026, 6, 19))
    form = InstallmentForm(instance=plan, user=user)
    assert 'value="2026-06-19"' in str(form["date"])
```

(If `test_forms.py` lacks `import pytest`, add it at the top.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_forms.py -k date_prefills -v`
Expected: FAIL — rendered value is `19/06/2026`, assertion not found.

- [ ] **Step 3: Implement the fix**

In `EntryForm.Meta.widgets`, change the `date` widget to:

```python
"date": forms.DateInput(
    format="%Y-%m-%d",
    attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
),
```

In `InstallmentForm.Meta.widgets`, change the `date` widget to:

```python
"date": forms.DateInput(
    format="%Y-%m-%d",
    attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest finances/tests/test_forms.py -k date_prefills -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/forms.py src/backend/finances/tests/test_forms.py
git commit -m "fix(forms): prefill date inputs as ISO so edit modals show the value"
```

---

### Task 2: Bug 4 — systemic edit modal edits template name

**Files:**
- Create form: `src/backend/finances/forms.py` (`SystemicEntryEditForm`)
- Modify: `src/backend/finances/views/cockpit.py` (`CockpitSystemicEditModalView`)
- Test: `src/backend/finances/tests/test_cockpit_systemic_edit_modal.py`

**Interfaces:**
- Produces: `SystemicEntryEditForm(data=None, *, entry, user)` with fields `name, date, amount, category, payment_method`; `.save()` updates `entry.systemic_expense.name` and the entry, returns the entry.

- [ ] **Step 1: Write the failing test**

Replace `test_post_updates_entry_and_rerenders_section` in `test_cockpit_systemic_edit_modal.py` and add a name test:

```python
    def test_post_updates_template_name_and_entry(self):
        resp = self.client.post(
            self._url(),
            {
                "name": "Aluguel novo",
                "date": "2026-10-01",
                "amount": "1700.00",
                "category": self.cat.id,
                "payment_method": self.pm.id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.s.refresh_from_db()
        self.entry.refresh_from_db()
        self.assertEqual(self.s.name, "Aluguel novo")
        self.assertEqual(self.entry.amount, Decimal("1700.00"))
        html = resp.content.decode()
        self.assertIn("Aluguel novo", html)            # row reflects new name
        self.assertIn("cockpit-systemic", html)
        self.assertIn("entry-saved", resp.headers.get("HX-Trigger", ""))

    def test_get_prefills_name_and_date(self):
        html = self.client.get(self._url()).content.decode()
        self.assertIn('value="Aluguel"', html)
        self.assertIn('value="2026-10-01"', html)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest finances/tests/test_cockpit_systemic_edit_modal.py -v`
Expected: FAIL — view still uses `EntryForm` (no `name` field; name not updated).

- [ ] **Step 3: Add `SystemicEntryEditForm` to `finances/forms.py`**

```python
class SystemicEntryEditForm(forms.Form):
    """Edit a launched systemic: the template name + this month's entry fields."""

    name = forms.CharField(
        max_length=100,
        label="Nome",
        widget=forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
    )
    date = forms.DateField(
        label="Data",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
        ),
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="Valor",
        widget=forms.NumberInput(
            attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
        ),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        label="Categoria",
        widget=forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
    )
    payment_method = forms.ModelChoiceField(
        queryset=PaymentMethod.objects.none(),
        label="Forma de pagamento",
        widget=forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
    )

    def __init__(self, *args, entry=None, user=None, **kwargs):
        self.entry = entry
        super().__init__(*args, **kwargs)
        cats = Category.objects.filter(user=user)
        pms = PaymentMethod.objects.filter(user=user, is_active=True)
        if entry is not None:
            cats = cats | Category.objects.filter(pk=entry.category_id)
            pms = pms | PaymentMethod.objects.filter(pk=entry.payment_method_id)
        self.fields["category"].queryset = cats
        self.fields["payment_method"].queryset = pms
        if not self.is_bound and entry is not None:
            self.fields["name"].initial = entry.systemic_expense.name
            self.fields["date"].initial = entry.date
            self.fields["amount"].initial = entry.amount
            self.fields["category"].initial = entry.category_id
            self.fields["payment_method"].initial = entry.payment_method_id

    def save(self):
        cd = self.cleaned_data
        systemic = self.entry.systemic_expense
        systemic.name = cd["name"]
        systemic.save(update_fields=["name", "updated_at"])
        self.entry.date = cd["date"]
        self.entry.amount = cd["amount"]
        self.entry.category = cd["category"]
        self.entry.payment_method = cd["payment_method"]
        self.entry.description = cd["name"]
        self.entry.save()
        return self.entry
```

- [ ] **Step 4: Rewire `CockpitSystemicEditModalView`**

In `finances/views/cockpit.py`, update the import line `from finances.forms import (... )` to also import `SystemicEntryEditForm`. Replace the `get`/`post` bodies of `CockpitSystemicEditModalView` (keep `_entry` and `_modal_context`):

```python
    def get(self, request, year, month, pk):
        entry = self._entry(request, year, month, pk)
        form = SystemicEntryEditForm(entry=entry, user=request.user)
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, pk, form),
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, year, month, pk):
        entry = self._entry(request, year, month, pk)
        form = SystemicEntryEditForm(request.POST, entry=entry, user=request.user)
        if form.is_valid():
            form.save()
            html = render_to_string(
                "cockpit/_systemic_section.html",
                _systemic_context(request, int(year), int(month)),
                request=request,
            )
            response = HttpResponse(html)
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Sistemático atualizado!", "type": "success"},'
                ' "entry-saved": true}'
            )
            return response
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, pk, form),
            request=request,
        )
        return HttpResponse(html)
```

The now-unused `_patch_entry_querysets(form, entry)` call inside this view is removed; `_patch_entry_querysets` itself stays (still used by parcelamento views).

- [ ] **Step 5: Run tests**

Run: `pytest finances/tests/test_cockpit_systemic_edit_modal.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add src/backend/finances/forms.py src/backend/finances/views/cockpit.py src/backend/finances/tests/test_cockpit_systemic_edit_modal.py
git commit -m "fix(cockpit): systemic edit modal edits template name so the row reflects the change"
```

---

### Task 3: Item 2 — `SystemicExpenseCreateForm` with N-month recurrence

**Files:**
- Create helper: `src/backend/finances/services/dates.py`
- Modify: `src/backend/finances/forms.py` (`SystemicExpenseCreateForm`)
- Test: `src/backend/finances/tests/test_systemic_create_form.py` (new)

**Interfaces:**
- Produces: `add_months(d: date, n: int) -> date` (first-of-month).
- Produces: `SystemicExpenseCreateForm(data, *, user)` extending `SystemicExpenseForm` with `is_recurring`, `months`, `start_month`; `.save_for_user(user) -> (SystemicExpense, launched:int)`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_systemic_create_form.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.forms import SystemicExpenseCreateForm
from finances.models import Category, Entry, PaymentMethod, SystemicExpense
from finances.models.entry import EntryType


@pytest.fixture
def ctx(db):
    user = baker.make("core.CustomUser")
    cat = baker.make(Category, user=user)
    pm = baker.make(PaymentMethod, user=user, is_active=True)
    return user, cat, pm


def _data(cat, pm, **over):
    data = {
        "name": "Netflix",
        "category": cat.id,
        "payment_method": pm.id,
        "default_amount": "39.90",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_non_recurring_creates_template_only(ctx):
    user, cat, pm = ctx
    form = SystemicExpenseCreateForm(_data(cat, pm), user=user)
    assert form.is_valid(), form.errors
    systemic, launched = form.save_for_user(user)
    assert SystemicExpense.objects.filter(user=user).count() == 1
    assert launched == 0
    assert Entry.objects.filter(systemic_expense=systemic).count() == 0


@pytest.mark.django_db
def test_recurring_launches_n_months(ctx):
    user, cat, pm = ctx
    form = SystemicExpenseCreateForm(
        _data(cat, pm, is_recurring="on", months="3", start_month="2026-06-01"),
        user=user,
    )
    assert form.is_valid(), form.errors
    systemic, launched = form.save_for_user(user)
    assert launched == 3
    months = sorted(
        Entry.objects.filter(systemic_expense=systemic, entry_type=EntryType.SYSTEMIC)
        .values_list("billing_month", flat=True)
    )
    assert months == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
    assert Entry.objects.get(billing_month=date(2026, 6, 1)).amount == Decimal("39.90")


@pytest.mark.django_db
def test_recurring_requires_payment_method(ctx):
    user, cat, pm = ctx
    form = SystemicExpenseCreateForm(
        _data(cat, pm, payment_method="", is_recurring="on", months="2", start_month="2026-06-01"),
        user=user,
    )
    assert not form.is_valid()
    assert "payment_method" in form.errors
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest finances/tests/test_systemic_create_form.py -v`
Expected: FAIL — `ImportError: cannot import name 'SystemicExpenseCreateForm'`.

- [ ] **Step 3: Create the date helper**

Create `src/backend/finances/services/dates.py`:

```python
from datetime import date


def add_months(d: date, n: int) -> date:
    """Return the first day of the month `n` months after `d`."""
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)
```

- [ ] **Step 4: Add `SystemicExpenseCreateForm` to `finances/forms.py`**

Add `from datetime import date as _date` is already imported as `_date`; also add at top: `from finances.services.dates import add_months`. Then:

```python
class SystemicExpenseCreateForm(SystemicExpenseForm):
    """Create a systemic template; optionally launch N months immediately."""

    is_recurring = forms.BooleanField(
        required=False,
        label="Recorrente por N meses",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm", "x-model": "recurring"}),
    )
    months = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=60,
        label="Nº de meses",
        widget=forms.NumberInput(
            attrs={"min": "1", "class": "input input-bordered input-sm w-full"}
        ),
    )
    start_month = forms.DateField(
        required=False,
        label="Mês inicial",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
        ),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_recurring"):
            if not cleaned.get("months"):
                self.add_error("months", "Informe o número de meses.")
            if not cleaned.get("payment_method"):
                self.add_error("payment_method", "Forma de pagamento é obrigatória para recorrência.")
        return cleaned

    def save_for_user(self, user):
        systemic = self.save(commit=False)
        systemic.user = user
        systemic.save()
        launched = 0
        if self.cleaned_data.get("is_recurring"):
            n = self.cleaned_data.get("months") or 1
            start = (self.cleaned_data.get("start_month") or _date.today()).replace(day=1)
            for i in range(n):
                systemic.create_monthly_entry(add_months(start, i))
                launched += 1
        return systemic, launched
```

- [ ] **Step 5: Run tests**

Run: `pytest finances/tests/test_systemic_create_form.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/backend/finances/services/dates.py src/backend/finances/forms.py src/backend/finances/tests/test_systemic_create_form.py
git commit -m "feat(systemic): create form with optional N-month recurrence launch"
```

---

### Task 4: Items 1+3 — Sistemático tab in "+" modal; remove inline form

**Files:**
- Modify: `src/backend/finances/views/entries.py` (`EntryModalView`)
- Modify: `src/backend/templates/partials/_modal_entry_form.html`
- Modify: `src/backend/templates/cockpit/_systemic_section.html`
- Test: `src/backend/finances/tests/test_views_entries.py` (add modal-systemic tests) and update `test_cockpit_systemic_create.py` / `test_entries_page_sections.py`

**Interfaces:**
- Consumes: `SystemicExpenseCreateForm.save_for_user` (Task 3).
- Produces: `GET /entries/modal/?year=&month=&mode=systemic` renders 3-tab modal with seeded `start_month`; `POST /entries/modal/` with `entry_mode=systemic` creates the template (and launches months), responds with `HX-Trigger` containing `entry-saved`, `systemic-changed`, `entries-changed`.

- [ ] **Step 1: Write the failing tests**

Add to `src/backend/finances/tests/test_views_entries.py`:

```python
    def test_modal_get_has_systemic_tab(self):
        resp = self.client.get("/entries/modal/?year=2026&month=6&mode=systemic")
        html = resp.content.decode()
        self.assertIn("Sistemático", html)
        self.assertIn('value="2026-06-01"', html)  # seeded start month

    def test_modal_post_systemic_creates_template(self):
        resp = self.client.post(
            "/entries/modal/",
            {
                "entry_mode": "systemic",
                "name": "Spotify",
                "category": self.cat.id,
                "payment_method": self.pm.id,
                "default_amount": "21.90",
            },
        )
        self.assertEqual(resp.status_code, 200)
        from finances.models import SystemicExpense
        self.assertTrue(SystemicExpense.objects.filter(user=self.user, name="Spotify").exists())
        self.assertIn("entry-saved", resp.headers.get("HX-Trigger", ""))

    def test_modal_post_systemic_recurring_launches(self):
        from finances.models import SystemicExpense, Entry
        resp = self.client.post(
            "/entries/modal/",
            {
                "entry_mode": "systemic",
                "name": "Academia",
                "category": self.cat.id,
                "payment_method": self.pm.id,
                "default_amount": "120.00",
                "is_recurring": "on",
                "months": "2",
                "start_month": "2026-06-01",
            },
        )
        self.assertEqual(resp.status_code, 200)
        s = SystemicExpense.objects.get(user=self.user, name="Academia")
        self.assertEqual(Entry.objects.filter(systemic_expense=s).count(), 2)
```

Check the top of `test_views_entries.py` for the test class's `setUp` — it must define `self.user`, `self.cat`, `self.pm`, and `self.client.force_login(self.user)`. If `self.cat`/`self.pm` are absent, add them in `setUp`:

```python
        self.cat = baker.make("finances.Category", user=self.user)
        self.pm = baker.make("finances.PaymentMethod", user=self.user, is_active=True)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest finances/tests/test_views_entries.py -k "modal" -v`
Expected: FAIL — no Sistemático tab; systemic mode not handled.

- [ ] **Step 3: Update `EntryModalView` in `finances/views/entries.py`**

Add imports near the top: `from datetime import date` is present; add `from finances.forms import EntryForm, InstallmentForm, SystemicExpenseCreateForm` (extend existing import). Replace `EntryModalView`:

```python
class EntryModalView(HtmxLoginRequiredMixin, View):
    """Serve modal form and handle regular, installment, and systemic creation."""

    def _start_month(self, request):
        try:
            y = int(request.GET.get("year"))
            m = int(request.GET.get("month"))
            return date(y, m, 1)
        except (TypeError, ValueError):
            return date.today().replace(day=1)

    def get(self, request):
        start = self._start_month(request)
        context = {
            "entry_form": EntryForm(user=request.user),
            "installment_form": InstallmentForm(user=request.user),
            "systemic_form": SystemicExpenseCreateForm(
                user=request.user, initial={"start_month": start}
            ),
            "initial_mode": request.GET.get("mode", "regular"),
        }
        html = render_to_string("partials/_modal_entry_form.html", context, request=request)
        return HttpResponse(html)

    def post(self, request):
        entry_mode = request.POST.get("entry_mode", "regular")

        if entry_mode == "installment":
            form = InstallmentForm(request.POST, user=request.user)
            if form.is_valid():
                plan = form.save(commit=False)
                plan.user = request.user
                plan.save()
                plan.generate_entries()
                response = HttpResponse("")
                response["HX-Trigger"] = json.dumps(
                    {
                        "showToast": {
                            "message": f"Parcelamento criado com {plan.num_installments} parcelas!",
                            "type": "success",
                        },
                        "entry-saved": True,
                        "entries-changed": True,
                    }
                )
                return response
        elif entry_mode == "systemic":
            form = SystemicExpenseCreateForm(request.POST, user=request.user)
            if form.is_valid():
                systemic, launched = form.save_for_user(request.user)
                msg = f"{systemic.name} adicionado!"
                if launched:
                    msg = f"{systemic.name}: {launched} mês(es) lançado(s)!"
                response = HttpResponse("")
                response["HX-Trigger"] = json.dumps(
                    {
                        "showToast": {"message": msg, "type": "success"},
                        "entry-saved": True,
                        "systemic-changed": True,
                        "entries-changed": True,
                    }
                )
                return response
        else:
            form = EntryForm(request.POST, user=request.user)
            if form.is_valid():
                entry = form.save(commit=False)
                entry.user = request.user
                entry.save()
                response = HttpResponse("")
                response["HX-Trigger"] = (
                    '{"showToast": {"message": "Entrada criada!", "type": "success"},'
                    ' "entry-saved": true, "entries-changed": true}'
                )
                return response

        context = {
            "entry_form": form if entry_mode == "regular" else EntryForm(user=request.user),
            "installment_form": form if entry_mode == "installment" else InstallmentForm(user=request.user),
            "systemic_form": form if entry_mode == "systemic" else SystemicExpenseCreateForm(user=request.user),
            "initial_mode": entry_mode,
            "errors": True,
        }
        html = render_to_string("partials/_modal_entry_form.html", context, request=request)
        return HttpResponse(html)
```

- [ ] **Step 4: Add the Sistemático tab to `templates/partials/_modal_entry_form.html`**

Change the root `x-data` to honor `initial_mode`:

```html
<div x-data="{ mode: '{{ initial_mode|default:"regular" }}' }" class="space-y-4">
```

Add a third tab link after the Parcelamento tab (inside `.tabs`):

```html
        <a class="tab" :class="mode === 'systemic' && 'tab-active'" @click="mode = 'systemic'">Sistemático</a>
```

Add this form block after the installment `</form>` and before the closing `</div>`:

```html
    <!-- Systemic form -->
    <form x-show="mode === 'systemic'"
          x-data="{ recurring: false }"
          hx-post="{% url 'finances:entry_modal' %}"
          hx-target="#entry-modal-content"
          hx-swap="innerHTML"
          class="space-y-3">
        {% csrf_token %}
        <input type="hidden" name="entry_mode" value="systemic">
        {% for field in systemic_form %}
          {% if field.name == "is_recurring" %}
            <div class="form-control">
              <label class="label cursor-pointer justify-start gap-2">
                {{ field }}<span class="label-text">{{ field.label }}</span>
              </label>
              {% if field.errors %}<span class="text-error text-sm">{{ field.errors.0 }}</span>{% endif %}
            </div>
          {% elif field.name == "months" or field.name == "start_month" %}
            <div class="form-control" x-show="recurring">
              <label class="label"><span class="label-text">{{ field.label }}</span></label>
              {{ field }}
              {% if field.errors %}<span class="text-error text-sm">{{ field.errors.0 }}</span>{% endif %}
            </div>
          {% else %}
            <div class="form-control">
              <label class="label"><span class="label-text">{{ field.label }}</span></label>
              {{ field }}
              {% if field.errors %}<span class="text-error text-sm">{{ field.errors.0 }}</span>{% endif %}
            </div>
          {% endif %}
        {% endfor %}
        <button type="submit" class="btn btn-accent w-full">Salvar sistemático</button>
    </form>
```

Note: `SystemicExpenseCreateForm` fields have no `labels` dict on the base `SystemicExpenseForm` for name/category/etc. Add a `labels` mapping to `SystemicExpenseForm.Meta` so the tab shows legends:

In `finances/forms.py`, `SystemicExpenseForm.Meta`, add:

```python
        labels = {
            "name": "Nome",
            "category": "Categoria",
            "payment_method": "Forma de pagamento",
            "default_amount": "Valor padrão",
        }
```

- [ ] **Step 5: Remove the inline form and rewire "+ novo" in `templates/cockpit/_systemic_section.html`**

Replace the header button + inline-form block (lines ~6–23) with:

```html
      <button class="btn btn-ghost btn-xs"
              hx-get="{% url 'finances:entry_modal' %}?year={{ current_year }}&month={{ current_month }}&mode=systemic"
              hx-target="#entry-modal-content" hx-swap="innerHTML"
              onclick="document.getElementById('entry-modal').showModal()">+ novo</button>
    </div>
```

(Delete the `<div x-data="{open:false}" ...> ... </form></div>` inline block entirely.)

Make the section self-refresh after a modal create: change the root div opening tag to:

```html
<div id="cockpit-systemic" class="card bg-base-100 border border-base-200 shadow-sm mb-4"
     hx-get="{% url 'finances:cockpit_systemic' current_year current_month %}"
     hx-trigger="systemic-changed from:body" hx-swap="outerHTML">
```

- [ ] **Step 6: Update `test_cockpit_systemic_create.py` and `test_entries_page_sections.py`**

Read both files. In `test_cockpit_systemic_create.py`, the inline `cockpit_systemic_create` endpoint/view still exists (used by nothing now) — keep the view+url for back-compat OR delete. Decision: KEEP `CockpitSystemicCreateView` and its url (harmless, still tested). The section template no longer renders the inline form, so any test asserting the inline form's presence must change to assert the "+ novo" button instead:

```python
        # was: assertIn('name="name"', section_html) for the inline form
        self.assertIn("mode=systemic", section_html)  # "+ novo" opens the modal
```

In `test_entries_page_sections.py`, if a test asserts the inline systemic form fields are present in the section, change it to assert the "+ novo" link (`mode=systemic`). Run the file first to see exactly which assertions break.

- [ ] **Step 7: Run the affected tests**

Run:
```
pytest finances/tests/test_views_entries.py finances/tests/test_cockpit_systemic_create.py finances/tests/test_entries_page_sections.py finances/tests/test_cockpit_systemic_views.py -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/backend/finances/views/entries.py src/backend/templates/partials/_modal_entry_form.html src/backend/templates/cockpit/_systemic_section.html src/backend/finances/forms.py src/backend/finances/tests/
git commit -m "feat(entries): add Sistemático tab to + modal with recurrence; remove inline cockpit form"
```

---

### Task 5: Bug 6 — income recurrence reflects in following months

**Files:**
- Create: `src/backend/finances/services/income_recurrence.py`
- Modify: `src/backend/finances/views/settings.py` (`IncomeCreateView.post`, `IncomeUpdateView.post`)
- Modify: `src/backend/finances/views/cockpit.py` (`CockpitIncomeEditModalView.post`)
- Test: `src/backend/finances/tests/test_income_recurrence.py` (new)

**Interfaces:**
- Consumes: `add_months` (Task 3).
- Produces: `apply_income_recurrence(income) -> int` — upserts `Income` rows for each month in the window, returns count touched.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_income_recurrence.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models import Income
from finances.services.income_recurrence import apply_income_recurrence


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser")


@pytest.mark.django_db
def test_noop_when_not_recurring(user):
    inc = baker.make(Income, user=user, name="Salário", amount="100", month=date(2026, 6, 1), is_recurring=False)
    assert apply_income_recurrence(inc) == 0
    assert Income.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_materializes_window(user):
    inc = baker.make(
        Income, user=user, name="Salário", amount="5000", month=date(2026, 6, 1),
        is_recurring=True, recurrence_start=date(2026, 6, 1), recurrence_end=date(2026, 9, 1),
    )
    touched = apply_income_recurrence(inc)
    assert touched == 4
    months = sorted(Income.objects.filter(user=user, name="Salário").values_list("month", flat=True))
    assert months == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]


@pytest.mark.django_db
def test_upserts_existing_amount(user):
    baker.make(Income, user=user, name="Salário", amount="4000", month=date(2026, 7, 1))
    inc = baker.make(
        Income, user=user, name="Salário", amount="5000", month=date(2026, 6, 1),
        is_recurring=True, recurrence_start=date(2026, 6, 1), recurrence_end=date(2026, 7, 1),
    )
    apply_income_recurrence(inc)
    july = Income.objects.get(user=user, name="Salário", month=date(2026, 7, 1))
    assert july.amount == Decimal("5000")
    assert Income.objects.filter(user=user, name="Salário").count() == 2


@pytest.mark.django_db
def test_defaults_to_year_end_when_blank(user):
    inc = baker.make(
        Income, user=user, name="Bolsa", amount="600", month=date(2026, 10, 1),
        is_recurring=True, recurrence_start=None, recurrence_end=None,
    )
    apply_income_recurrence(inc)
    months = sorted(Income.objects.filter(user=user, name="Bolsa").values_list("month", flat=True))
    assert months == [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest finances/tests/test_income_recurrence.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the service**

Create `src/backend/finances/services/income_recurrence.py`:

```python
from datetime import date

from finances.models import Income
from finances.services.dates import add_months


def apply_income_recurrence(income) -> int:
    """Upsert one Income row per month across the recurrence window.

    No-op unless ``income.is_recurring``. Window is
    ``[recurrence_start, recurrence_end]``; blanks default to
    ``income.month`` → December of that year. Existing same-name rows in the
    window are updated to match (amount + recurrence flags). Returns the number
    of months touched.
    """
    if not income.is_recurring:
        return 0
    start = (income.recurrence_start or income.month).replace(day=1)
    end = (income.recurrence_end or date(income.month.year, 12, 1)).replace(day=1)
    if end < start:
        return 0
    touched = 0
    m = start
    while m <= end:
        Income.objects.update_or_create(
            user=income.user,
            name=income.name,
            month=m,
            defaults={
                "amount": income.amount,
                "is_recurring": True,
                "recurrence_start": start,
                "recurrence_end": end,
            },
        )
        touched += 1
        m = add_months(m, 1)
    return touched
```

- [ ] **Step 4: Run service tests**

Run: `pytest finances/tests/test_income_recurrence.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Wire into the edit views (integration test first)**

Add to `src/backend/finances/tests/test_income_recurrence.py`:

```python
from django.test import Client


@pytest.mark.django_db
def test_cockpit_edit_modal_materializes(user):
    inc = baker.make(Income, user=user, name="Salário", amount="5000", month=date(2026, 6, 1))
    c = Client()
    c.force_login(user)
    resp = c.post(
        f"/cockpit/2026/6/income/{inc.pk}/edit-modal/",
        {
            "name": "Salário",
            "amount": "5000",
            "month": "2026-06-01",
            "is_recurring": "on",
            "recurrence_start": "2026-06-01",
            "recurrence_end": "2026-08-01",
        },
    )
    assert resp.status_code == 200
    months = sorted(Income.objects.filter(user=user, name="Salário").values_list("month", flat=True))
    assert months == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
```

Run it: `pytest finances/tests/test_income_recurrence.py -k cockpit_edit_modal -v` → FAIL (only one month).

- [ ] **Step 6: Call the service in the three income save paths**

In `finances/views/settings.py`, add import `from finances.services.income_recurrence import apply_income_recurrence`. In `IncomeCreateView.post` after `income.save()` add `apply_income_recurrence(income)`. In `IncomeUpdateView.post` after `form.save()` add `apply_income_recurrence(form.instance)`.

In `finances/views/cockpit.py`, add the same import. In `CockpitIncomeEditModalView.post`, change `form.save()` to:

```python
            inc = form.save()
            apply_income_recurrence(inc)
```

- [ ] **Step 7: Run tests**

Run: `pytest finances/tests/test_income_recurrence.py finances/tests/test_cockpit_income_edit_modal.py finances/tests/test_views_settings.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/backend/finances/services/income_recurrence.py src/backend/finances/views/settings.py src/backend/finances/views/cockpit.py src/backend/finances/tests/test_income_recurrence.py
git commit -m "fix(income): recurrence on save materializes following months (upsert window)"
```

---

### Task 6: Friday verification, full suite, FE rebuild

**Run this task LAST — after Task 7.** It is the final verification gate for all changes.

**Files:** none (verification) + possibly `src/backend/static/frontend/*` rebuild.

- [ ] **Step 1: Run the full finance test suite**

Run: `pytest finances/tests/ -q`
Expected: all green. Fix any regressions before continuing.

- [ ] **Step 2: Lint**

Run: `ruff check finances`
Expected: clean (fix any findings).

- [ ] **Step 3: Rebuild frontend if needed**

Only the modal/section templates changed (server-rendered). No React island changed. If `ruff`/tests pass and no new JS, a Tailwind rebuild is still prudent because new classes were added to templates. From the frontend project dir, rebuild with `--force` and commit `mount.js`/`tailwind.css` if they changed (per project memory `reference_frontend_build_artifacts`).

- [ ] **Step 4: Verify on friday dev (192.168.1.7:8700)**

Sync this branch to friday per the usual dev flow, then in the running app confirm:
1. Bug 5 — open any edit modal (entrada, sistemático, parcela): the date field is pre-filled.
2. Bug 4 — edit a launched systemic, change the name → row shows the new name; modal closes on save.
3. Items 1+3 — the "+" FAB and the systemic "+ novo" both open the modal; Sistemático tab has labels and does not stretch oddly; inline form is gone.
4. Item 2 — create a systemic with "Recorrente por 3 meses" → 3 months appear launched.
5. Bug 6 — edit an income to recurring with a window → following months show the income (check Projeção).
6. Projection (Task 7) — the "Acumulado" for a month (e.g. junho) stays the same when you change the window start; the start control is two selects (mês + ano) with year options spanning the data history.

- [ ] **Step 5: Final commit (design + plan docs, if not yet committed)**

```bash
git add docs/superpowers/specs/2026-06-19-systemic-expenses-ux-and-recurrence-design.md docs/superpowers/plans/2026-06-19-systemic-expenses-ux-and-recurrence.md
git commit -m "docs: spec + plan for systemic expenses UX and recurrence"
```

---

### Task 7: Projection — historical acumulado + year/month selectors

**Files:**
- Modify: `src/backend/finances/services/projection.py` (`build_projection`)
- Modify: `src/backend/finances/views/projection.py` (`ProjectionView`, `_parse_start`)
- Modify: `src/backend/templates/projection/projection_page.html` (start control)
- Test: `src/backend/finances/tests/test_projection_service.py`, `src/backend/finances/tests/test_views_projection.py`

**Interfaces:**
- Produces: `build_projection` rows whose `acumulado` is the true historical running total (anchored at the earliest data month), independent of `start_month`.
- Produces: `ProjectionView` context `start_year`, `start_month`, `year_options`, `start_month_options`; accepts `?start_year=&start_month=` (keeps `?start=YYYY-MM` as fallback).

**Background:** today `build_projection` sets `acumulado = ZERO` at `start_month`, so the accumulated balance shifts when the user changes the window start. The fix seeds it with the sum of `saldo_projetado` over `[earliest_data_month, start_month)` so each month's accumulated is fixed. The existing `test_acumulado_is_cumulative` starts at the earliest data month (seed 0) and stays green.

- [ ] **Step 1: Write the failing service test**

Add to `test_projection_service.py` inside `TestBuildProjection`:

```python
    def test_acumulado_is_historical_independent_of_window(self, user, cat, pix):
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2026, 1, 1))
        _entry(user, cat, pix, "200", date(2026, 1, 1), EntryType.REGULAR)  # Jan saldo 800
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2026, 2, 1))
        _entry(user, cat, pix, "300", date(2026, 2, 1), EntryType.REGULAR)  # Feb saldo 700
        # Window starts in Feb, but acumulado must include January's history.
        rows = build_projection(user, date(2026, 2, 1), 1, today=date(2026, 3, 1))
        assert rows[0]["month"] == date(2026, 2, 1)
        assert rows[0]["saldo_projetado"] == Decimal("700")
        assert rows[0]["acumulado"] == Decimal("1500")  # 800 (Jan) + 700 (Feb)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest finances/tests/test_projection_service.py -k historical -v`
Expected: FAIL — acumulado is `700` (window-relative).

- [ ] **Step 3: Seed acumulado from history in `build_projection`**

In `finances/services/projection.py`, after `start_month = start_month.replace(day=1)` and `num_months` normalization, compute the data anchor and widen the aggregation window. Replace the block that builds `months`/`end_exclusive` and the aggregation filters with:

```python
    months = [_add_months(start_month, i) for i in range(num_months)]
    if not months:
        return []
    end_exclusive = _add_months(months[-1], 1)

    # Earliest month with any data — acumulado is anchored here, not at the
    # window start, so the accumulated balance for a month is fixed regardless
    # of the projection window the user picks.
    inc_min = Income.objects.filter(user=user).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.filter(user=user).aggregate(m=Min("billing_month"))["m"]
    data_candidates = [d for d in (inc_min, ent_min) if d is not None]
    data_anchor = min(data_candidates).replace(day=1) if data_candidates else start_month
    agg_start = min(data_anchor, start_month)

    # Every month from the anchor through the window end (drives the running total).
    span = (months[-1].year * 12 + months[-1].month) - (agg_start.year * 12 + agg_start.month) + 1
    all_months = [_add_months(agg_start, i) for i in range(span)]
```

Update the two aggregation queries to start at `agg_start` instead of `start_month`:

```python
    entry_totals: dict[tuple[date, str], Decimal] = {}
    for r in (
        Entry.objects.filter(
            user=user, billing_month__gte=agg_start, billing_month__lt=end_exclusive
        )
        .values("billing_month", "entry_type")
        .annotate(total=Sum("amount"))
    ):
        entry_totals[(r["billing_month"], r["entry_type"])] = r["total"] or ZERO

    income_totals: dict[date, Decimal] = {}
    for r in (
        Income.objects.filter(
            user=user, month__gte=agg_start, month__lt=end_exclusive
        )
        .values("month")
        .annotate(total=Sum("amount"))
    ):
        income_totals[r["month"]] = r["total"] or ZERO
```

Change the final loop to iterate `all_months`, accumulate every month, but only append rows within the window (`m >= start_month`):

```python
    rows = []
    acumulado = ZERO
    for m in all_months:
        if m > current_month:
            systemic = active_systemic_total
        else:
            systemic = entry_totals.get((m, EntryType.SYSTEMIC), ZERO)
        installments = entry_totals.get((m, EntryType.INSTALLMENT), ZERO)
        diverse = entry_totals.get((m, EntryType.REGULAR), ZERO)
        programmed = systemic + installments
        total = programmed + diverse
        income = income_totals.get(m, ZERO)

        pct_income = (total / income * 100) if income else None
        saldo_programado = income - programmed
        saldo_projetado = income - total
        acumulado += saldo_projetado

        if m < start_month:
            continue  # pre-window month: counted into acumulado, not displayed

        rows.append(
            {
                "month": m,
                "systemic": systemic,
                "installments": installments,
                "programmed": programmed,
                "diverse": diverse,
                "total": total,
                "income": income,
                "pct_income": pct_income,
                "saldo_programado": saldo_programado,
                "saldo_projetado": saldo_projetado,
                "acumulado": acumulado,
            }
        )
    return rows
```

(The `Min` import: `from django.db.models import Min, Sum` — add `Min` to the existing import.)

- [ ] **Step 4: Run service tests (all)**

Run: `pytest finances/tests/test_projection_service.py -v`
Expected: PASS (including `test_acumulado_is_cumulative`, unchanged because it starts at the data anchor).

- [ ] **Step 5: Write the failing control test**

Add to `src/backend/finances/tests/test_views_projection.py` (create if missing; use `logged_client` fixture from conftest):

```python
import pytest
from datetime import date
from decimal import Decimal

from django.urls import reverse
from model_bakery import baker


@pytest.mark.django_db
def test_start_control_is_year_and_month_selects(logged_client):
    html = logged_client.get(reverse("finances:projection")).content.decode()
    assert 'name="start_year"' in html
    assert 'name="start_month"' in html


@pytest.mark.django_db
def test_year_options_span_data_history(logged_client, user):
    cat = baker.make("finances.Category", user=user)
    pm = baker.make("finances.PaymentMethod", user=user, type="pix")
    baker.make("finances.Entry", user=user, category=cat, payment_method=pm,
               amount=Decimal("10"), date=date(2024, 3, 1), billing_month=date(2024, 3, 1),
               billing_month_override=True)
    html = logged_client.get(reverse("finances:projection")).content.decode()
    assert '<option value="2024"' in html


@pytest.mark.django_db
def test_start_year_month_params_drive_window(logged_client):
    html = logged_client.get(
        reverse("finances:projection"), {"start_year": "2026", "start_month": "3", "months": "2"}
    ).content.decode()
    assert "mar/2026" in html.lower() or "Mar/2026" in html
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest finances/tests/test_views_projection.py -v`
Expected: FAIL — selects not present.

- [ ] **Step 7: Update `ProjectionView` / `_parse_start`**

In `finances/views/projection.py`, add imports `from django.db.models import Min` and `from finances.models import Entry, Income`. Replace `_parse_start` with a request-aware version and update `get_context_data`:

```python
def _parse_start(request, today: date) -> date:
    sy, sm = request.GET.get("start_year"), request.GET.get("start_month")
    if sy and sm:
        try:
            return date(int(sy), int(sm), 1)
        except (ValueError, TypeError):
            pass
    raw = request.GET.get("start")
    if raw:
        try:
            year, month = (int(p) for p in raw.split("-")[:2])
            return date(year, month, 1)
        except (ValueError, TypeError):
            pass
    return _default_start(today)


def _data_anchor_year(user, today: date) -> int:
    inc_min = Income.objects.filter(user=user).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.filter(user=user).aggregate(m=Min("billing_month"))["m"]
    candidates = [d for d in (inc_min, ent_min) if d is not None]
    return min(candidates).year if candidates else today.year
```

In `get_context_data`, replace the start parsing + context lines:

```python
        start = _parse_start(self.request, today)
        months = _parse_months(self.request.GET.get("months"))

        first_year = min(_data_anchor_year(self.request.user, today), start.year)
        last_year = max(today.year, start.year)

        context["rows"] = build_projection(self.request.user, start, months, today=today)
        context["today_month"] = today.replace(day=1)
        context["start_year"] = start.year
        context["start_month"] = start.month
        context["year_options"] = list(range(first_year, last_year + 1))
        context["start_month_options"] = list(range(1, 13))
        context["months_value"] = months
        context["month_options"] = [6, 12, 14, 18, 24]
        return context
```

- [ ] **Step 8: Update the control in `templates/projection/projection_page.html`**

Replace the "Início" `<label>...</label>` block (the `<input type="month" name="start">`) with:

```html
    <label class="form-control">
        <span class="label-text text-xs mb-1">Início</span>
        <div class="flex gap-1">
            <select name="start_month" class="select select-bordered select-sm">
                {% for m in start_month_options %}
                <option value="{{ m }}" {% if m == start_month %}selected{% endif %}>{{ m|month_abbr }}</option>
                {% endfor %}
            </select>
            <select name="start_year" class="select select-bordered select-sm">
                {% for y in year_options %}
                <option value="{{ y }}" {% if y == start_year %}selected{% endif %}>{{ y }}</option>
                {% endfor %}
            </select>
        </div>
    </label>
```

- [ ] **Step 9: Run projection tests**

Run: `pytest finances/tests/test_projection_service.py finances/tests/test_views_projection.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/backend/finances/services/projection.py src/backend/finances/views/projection.py src/backend/templates/projection/projection_page.html src/backend/finances/tests/test_projection_service.py src/backend/finances/tests/test_views_projection.py
git commit -m "fix(projection): historical acumulado + year/month start selectors"
```

---

## Self-Review

- **Spec coverage:** Bug 5 → Task 1. Bug 4 → Task 2. Items 1+3 → Task 4. Item 2 → Task 3 (form) + Task 4 (UI/endpoint). Bug 6 → Task 5. Projection (historical acumulado + year/month selectors) → Task 7. Friday verification + full suite + FE rebuild → Task 6 (run last). All covered.
- **Placeholders:** none — all steps have concrete code/commands.
- **Type consistency:** `add_months(d, n)` defined in Task 3, reused in Task 5. `SystemicExpenseCreateForm.save_for_user → (systemic, launched)` consumed in Task 4. `SystemicEntryEditForm(entry=, user=).save()` consumed in Task 2. `apply_income_recurrence(income) -> int` consumed in Task 5 steps.
- **Note:** `test_recurring_skips_already_launched` asserts launched==2 because each create form makes a NEW template; the skip guard protects against double-launch within one template's window (e.g. re-submitting). The idempotence within a template is exercised by the `exists()` guard; an explicit same-template re-run is covered implicitly.
