import csv
import os
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.views import View

from finances.models import Category, Entry, EntryType, InstallmentPlan, PaymentMethod
from finances.services.billing import compute_billing_month, resolve_closing_day
from finances.services.csv_parser import detect_columns, parse_csv_rows


class ImportUploadView(LoginRequiredMixin, View):
    """Step 1: Upload CSV file and select import type."""

    def get(self, request):
        return render(request, "importer/import_page.html", {"step": "upload"})

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        import_type = request.POST.get("import_type", "regular")

        if not uploaded_file:
            return render(
                request,
                "importer/import_page.html",
                {"step": "upload", "error": "Selecione um arquivo CSV."},
            )

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # Read headers for auto-detection
        try:
            with open(tmp_path, encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader)
        except UnicodeDecodeError:
            return render(
                request,
                "importer/import_page.html",
                {
                    "step": "upload",
                    "error": "Arquivo não está em formato UTF-8. Re-exporte do Google Sheets.",
                },
            )

        # Store in session
        request.session["import_data"] = {
            "file_path": tmp_path,
            "import_type": import_type,
            "headers": headers,
        }

        return redirect("finances:import_map")


class ImportMappingView(LoginRequiredMixin, View):
    """Step 2: Review and confirm column mapping."""

    def get(self, request):
        import_data = request.session.get("import_data")
        if not import_data:
            return redirect("finances:import_upload")

        headers = import_data["headers"]
        import_type = import_data["import_type"]
        mapping = detect_columns(headers, import_type)

        # Determine which fields are needed
        if import_type == "installment":
            fields = [
                "date",
                "total_amount",
                "description",
                "category",
                "payment_method",
                "num_installments",
                "installment_amount",
            ]
        else:
            fields = ["date", "amount", "description", "category", "payment_method"]

        return render(
            request,
            "importer/import_page.html",
            {
                "step": "mapping",
                "mapping": mapping,
                "headers": headers,
                "headers_indexed": list(enumerate(headers)),
                "fields": fields,
                "import_type": import_type,
            },
        )

    def post(self, request):
        import_data = request.session.get("import_data")
        if not import_data:
            return redirect("finances:import_upload")

        # Build mapping from form data
        import_type = import_data["import_type"]
        if import_type == "installment":
            fields = [
                "date",
                "total_amount",
                "description",
                "category",
                "payment_method",
                "num_installments",
                "installment_amount",
            ]
        else:
            fields = ["date", "amount", "description", "category", "payment_method"]

        mapping = {}
        for field in fields:
            val = request.POST.get(field)
            if val is not None:
                mapping[field] = int(val)

        # Parse rows
        with open(import_data["file_path"], encoding="utf-8") as f:
            rows = parse_csv_rows(f, mapping, import_type)

        # Find unmatched categories and payment methods
        user = request.user
        existing_categories = {
            c.lower(): c for c in Category.objects.filter(user=user).values_list("name", flat=True)
        }
        existing_pms = {
            p.lower(): p
            for p in PaymentMethod.objects.filter(user=user).values_list("name", flat=True)
        }

        unmatched_categories = set()
        unmatched_pms = set()
        for row in rows:
            if row["status"] == "ok":
                cat = row.get("category", "")
                if cat and cat.lower() not in existing_categories:
                    unmatched_categories.add(cat)
                pm = row.get("payment_method", "")
                if pm and pm.lower() not in existing_pms:
                    unmatched_pms.add(pm)

        # Check duplicates
        duplicate_indices = []
        amount_field = "total_amount" if import_type == "installment" else "amount"
        for i, row in enumerate(rows):
            if row["status"] != "ok":
                continue
            if import_type == "installment":
                exists = InstallmentPlan.objects.filter(
                    user=user,
                    date=row["date"],
                    total_amount=Decimal(row["total_amount"]),
                    description=row["description"],
                ).exists()
            else:
                exists = Entry.objects.filter(
                    user=user,
                    date=row["date"],
                    amount=Decimal(row[amount_field]),
                    description=row["description"],
                ).exists()
            if exists:
                row["status"] = "duplicate"
                duplicate_indices.append(i)

        # Store in session
        import_data["column_mapping"] = mapping
        import_data["rows"] = rows
        import_data["unmatched_categories"] = sorted(unmatched_categories)
        import_data["unmatched_pms"] = sorted(unmatched_pms)
        import_data["duplicate_indices"] = duplicate_indices
        import_data["skip_indices"] = []
        request.session["import_data"] = import_data
        request.session.modified = True

        return redirect("finances:import_preview")


class ImportPreviewView(LoginRequiredMixin, View):
    """Step 3: Preview parsed rows with warnings."""

    def get(self, request):
        import_data = request.session.get("import_data")
        if not import_data or "rows" not in import_data:
            return redirect("finances:import_upload")

        rows = import_data["rows"]
        ok_count = sum(1 for r in rows if r["status"] == "ok")
        dup_count = sum(1 for r in rows if r["status"] == "duplicate")
        err_count = sum(1 for r in rows if r["status"] == "error")

        # Get existing categories/PMs for resolution dropdowns
        categories = Category.objects.filter(user=request.user).order_by("name")
        payment_methods = PaymentMethod.objects.filter(user=request.user, is_active=True).order_by(
            "name"
        )

        return render(
            request,
            "importer/import_page.html",
            {
                "step": "preview",
                "rows": rows,
                "ok_count": ok_count,
                "dup_count": dup_count,
                "err_count": err_count,
                "import_type": import_data["import_type"],
                "unmatched_categories": import_data.get("unmatched_categories", []),
                "unmatched_pms": import_data.get("unmatched_pms", []),
                "categories": categories,
                "payment_methods": payment_methods,
                "skip_indices": import_data.get("skip_indices", []),
            },
        )

    def post(self, request):
        """Handle conflict resolution and skip toggling."""
        import_data = request.session.get("import_data")
        if not import_data:
            return redirect("finances:import_upload")

        # Process skip toggles
        skip_indices = []
        for key, value in request.POST.items():
            if key.startswith("skip_") and value == "on":
                idx = int(key.replace("skip_", ""))
                skip_indices.append(idx)
        import_data["skip_indices"] = skip_indices

        # Process category resolutions
        category_resolutions = {}
        for key, value in request.POST.items():
            if key.startswith("cat_resolve_") and value:
                cat_name = key.replace("cat_resolve_", "")
                category_resolutions[cat_name] = value
        import_data["category_resolutions"] = category_resolutions

        # Process PM resolutions
        pm_resolutions = {}
        for key, value in request.POST.items():
            if key.startswith("pm_resolve_") and value:
                pm_name = key.replace("pm_resolve_", "")
                pm_resolutions[pm_name] = value
        import_data["pm_resolutions"] = pm_resolutions

        request.session["import_data"] = import_data
        request.session.modified = True

        return redirect("finances:import_preview")


class ImportExecuteView(LoginRequiredMixin, View):
    """Step 4: Execute the import."""

    @transaction.atomic
    def post(self, request):
        import_data = request.session.get("import_data")
        if not import_data or "rows" not in import_data:
            return redirect("finances:import_upload")

        rows = import_data["rows"]
        import_type = import_data["import_type"]
        skip_indices = set(import_data.get("skip_indices", []))
        category_resolutions = import_data.get("category_resolutions", {})
        pm_resolutions = import_data.get("pm_resolutions", {})
        user = request.user

        # Build category and PM lookup maps (case-insensitive)
        cat_map = {c.name.lower(): c for c in Category.objects.filter(user=user)}
        pm_map = {p.name.lower(): p for p in PaymentMethod.objects.filter(user=user)}

        # Create new categories/PMs from resolutions
        for name, resolution in category_resolutions.items():
            if resolution == "__new__" and name.lower() not in cat_map:
                new_cat = Category.objects.create(user=user, name=name)
                cat_map[name.lower()] = new_cat

        for name, resolution in pm_resolutions.items():
            if resolution == "__new__" and name.lower() not in pm_map:
                new_pm = PaymentMethod.objects.create(user=user, name=name, type="pix")
                pm_map[name.lower()] = new_pm

        created_count = 0
        skipped_count = 0
        error_count = 0

        for i, row in enumerate(rows):
            if i in skip_indices:
                skipped_count += 1
                continue
            if row["status"] == "error":
                error_count += 1
                continue
            cat_name = row.get("category", "")
            pm_name = row.get("payment_method", "")

            # Resolve category (case-insensitive lookup)
            category = cat_map.get(cat_name.lower())
            if not category and cat_name in category_resolutions:
                res = category_resolutions[cat_name]
                if res != "__new__":
                    category = Category.objects.filter(user=user, pk=res).first()
            if not category:
                error_count += 1
                continue

            # Resolve payment method (case-insensitive lookup)
            payment_method = pm_map.get(pm_name.lower())
            if not payment_method and pm_name in pm_resolutions:
                res = pm_resolutions[pm_name]
                if res != "__new__":
                    payment_method = PaymentMethod.objects.filter(user=user, pk=res).first()
            if not payment_method:
                error_count += 1
                continue

            try:
                if import_type == "installment":
                    entry_date = date.fromisoformat(row["date"])
                    plan = InstallmentPlan.objects.create(
                        user=user,
                        date=entry_date,
                        description=row["description"],
                        category=category,
                        payment_method=payment_method,
                        total_amount=Decimal(row["total_amount"]),
                        num_installments=int(row["num_installments"]),
                        installment_amount=Decimal(row["installment_amount"]),
                    )
                    plan.generate_entries()
                else:
                    entry_date = date.fromisoformat(row["date"])
                    billing_month = compute_billing_month(
                        entry_date,
                        payment_method.type,
                        resolve_closing_day(payment_method, entry_date),
                    )
                    Entry.objects.create(
                        user=user,
                        date=entry_date,
                        amount=Decimal(row["amount"]),
                        description=row["description"],
                        category=category,
                        payment_method=payment_method,
                        entry_type=EntryType.REGULAR,
                        billing_month=billing_month,
                        billing_month_override=False,
                    )
                created_count += 1
            except Exception:
                error_count += 1

        # Clean up temp file and session
        file_path = import_data.get("file_path")
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
        if "import_data" in request.session:
            del request.session["import_data"]

        return render(
            request,
            "importer/import_page.html",
            {
                "step": "result",
                "created_count": created_count,
                "skipped_count": skipped_count,
                "error_count": error_count,
                "import_type": import_type,
            },
        )
