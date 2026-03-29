from django.db import connection
from django.http import JsonResponse


def health_check(request):
    """Health check endpoint for Cloud Run startup/liveness probes."""
    db_status = "ok"
    try:
        connection.ensure_connection()
    except Exception:
        db_status = "error"

    status = "ok" if db_status == "ok" else "degraded"
    status_code = 200 if status == "ok" else 503

    return JsonResponse({"status": status, "database": db_status}, status=status_code)
