"""Hand a TaskRun to Cloud Tasks.

Only the row's *id* travels in the body. The payload already lives on the
TaskRun, so the wire format stays tiny no matter what the work is, and the
fixed 1 MiB task ceiling stops being something every caller has to reason
about. ``enqueue`` still refuses an oversized payload, because the row is not
free either.
"""

import json

from django.conf import settings

from core.middleware import REQUEST_ID_HEADER
from core.models import TaskRun


class CloudTasksBackend:
    def __init__(self, client=None):
        # Injectable so a test can assert the request shape without
        # credentials, a network, or a GCP project.
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from google.cloud import tasks_v2

            self._client = tasks_v2.CloudTasksClient()
        return self._client

    def dispatch(self, task_run: TaskRun) -> None:
        from google.cloud import tasks_v2

        base = settings.CLOUD_TASKS_TARGET_BASE_URL.rstrip("/")
        url = f"{base}/tasks/{task_run.name}/"

        headers = {"Content-Type": "application/json"}
        # The originating request's ID, forwarded so the task's own log lines
        # carry it (S10-5). `request_id_middleware` adopts a well-formed
        # inbound value via `core.request_id.sanitise_inbound`, so no new
        # plumbing is needed — and both are 32 hex chars, which is exactly what
        # that function accepts. Omitted when empty: an empty header would be
        # replaced by a fresh ID, silently breaking the link it exists to make.
        if task_run.request_id:
            headers[REQUEST_ID_HEADER] = task_run.request_id

        task = tasks_v2.Task(
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=url,
                headers=headers,
                body=json.dumps({"task_run_id": str(task_run.id)}).encode(),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=settings.CLOUD_TASKS_OIDC_SERVICE_ACCOUNT,
                    # Must match CLOUD_TASKS_AUDIENCE, which `core.tasks.auth`
                    # verifies the token against. A mismatch is a 403 that
                    # looks like a configuration problem somewhere else.
                    audience=settings.CLOUD_TASKS_AUDIENCE,
                ),
            ),
        )
        self.client.create_task(
            tasks_v2.CreateTaskRequest(
                parent=self.client.queue_path(
                    settings.CLOUD_TASKS_PROJECT,
                    settings.CLOUD_TASKS_LOCATION,
                    settings.CLOUD_TASKS_QUEUE,
                ),
                task=task,
            )
        )
