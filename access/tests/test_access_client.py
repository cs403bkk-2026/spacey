"""access/client.py + access/functions.py: the hub's link to spacey-access.

Unit tests only (no network, CI-safe): urlopen is replaced, and the answers are
the examples from spacey-access/openapi.yaml 0.2.0. The real service is checked
by the local orchestration (spacey-access/orchestration), never in CI.
"""

import io
import json
import socket
from urllib.error import HTTPError, URLError

import pytest
from flask import Flask

from access import client, functions

RECORD = {"booking_id": 42, "access_code": "3f9a0c1b", "status": "available",
          "expires_at": "2026-12-01T12:00:00+00:00", "checked_in_at": None,
          "checked_out_at": None, "revoked_at": None, "expired_at": None}
CONFLICT = {"error": "access is revoked", "status": "revoked"}


class Answer:
    def __init__(self, status, body):
        self.status, self._raw = status, json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def service(monkeypatch):
    """Records each request and answers with the next queued (status, body)."""
    monkeypatch.setenv("ACCESS_URL", "http://access.test/")
    monkeypatch.setenv("SERVICE_TOKEN", "test-token")
    sent, queue = [], []

    def fake_urlopen(request, timeout):
        sent.append({"method": request.get_method(), "url": request.full_url,
                     "auth": request.get_header("Authorization"),
                     "body": json.loads(request.data) if request.data else None,
                     "timeout": timeout})
        status, body = queue.pop(0)
        if isinstance(status, Exception):
            raise status
        if status >= 400:
            raise HTTPError(request.full_url, status, "", {}, io.BytesIO(json.dumps(body).encode()))
        return Answer(status, body)

    monkeypatch.setattr(client, "urlopen", fake_urlopen)
    return sent, queue


CASES = [
    ("create_access", (42, "2026-12-01T10:00:00+00:00", "2026-12-01T12:00:00+00:00"),
     "POST", "/bookings/42/access",
     {"start_time": "2026-12-01T10:00:00+00:00", "end_time": "2026-12-01T12:00:00+00:00"}, 201),
    ("read_access", (42,), "GET", "/bookings/42/access", None, 200),
    ("revoke_access", (42,), "POST", "/bookings/42/access/revoke", None, 200),
    ("check_in", (42, "3f9a0c1b"), "POST", "/bookings/42/check-in", {"access_code": "3f9a0c1b"}, 200),
    ("check_out", (42,), "POST", "/bookings/42/check-out", None, 200),
    ("expire_access", (42,), "POST", "/bookings/42/access/expire", None, 200),
]


@pytest.mark.parametrize("name, args, method, path, body, status", CASES, ids=[c[0] for c in CASES])
def test_each_function_makes_its_one_call_with_the_token(service, name, args, method, path, body, status):
    sent, queue = service
    queue.append((status, RECORD))

    payload, got = getattr(functions, name)(*args)

    assert (payload, got) == (RECORD, status)
    assert len(sent) == 1
    assert sent[0]["method"] == method
    assert sent[0]["url"] == "http://access.test" + path
    assert sent[0]["auth"] == "Bearer test-token"
    assert sent[0]["body"] == body
    assert sent[0]["timeout"] == client.TIMEOUT_S


def test_create_sends_datetimes_as_iso_8601(service):
    from datetime import datetime, timezone
    sent, queue = service
    queue.append((201, RECORD))

    functions.create_access(42, datetime(2026, 12, 1, 10, tzinfo=timezone.utc),
                            datetime(2026, 12, 1, 12, tzinfo=timezone.utc))

    assert sent[0]["body"] == {"start_time": "2026-12-01T10:00:00+00:00",
                               "end_time": "2026-12-01T12:00:00+00:00"}


@pytest.mark.parametrize("name, args, status, body", [
    ("create_access", (42, "a", "b"), 200, RECORD),
    ("read_access", (42,), 404, {"error": "access record not found"}),
    ("revoke_access", (42,), 409, CONFLICT),
    ("check_in", (42, "wrong"), 403, {"error": "wrong access code"}),
    ("check_out", (42,), 409, {"error": "not checked in", "status": "available"}),
    ("expire_access", (42,), 404, {"error": "access record not found"}),
])
def test_contract_refusals_are_passed_through_unchanged(service, name, args, status, body):
    _, queue = service
    queue.append((status, body))

    assert getattr(functions, name)(*args) == (body, status)


@pytest.mark.parametrize("failure", [
    503, 500, 401,
    URLError("connection refused"), socket.timeout("timed out"),
], ids=["503", "500", "401-token", "refused", "timeout"])
def test_failures_raise_access_unavailable(service, failure):
    _, queue = service
    queue.append((failure, {"error": "x"}))

    with pytest.raises(client.AccessUnavailable):
        functions.read_access(42)


def test_a_non_json_answer_is_unavailable(service, monkeypatch):
    _, queue = service

    class NotJson(Answer):
        def read(self):
            return b"<html>proxy error</html>"

    monkeypatch.setattr(client, "urlopen", lambda request, timeout: NotJson(200, None))
    with pytest.raises(client.AccessUnavailable):
        functions.read_access(42)


@pytest.mark.parametrize("value, expected", [(None, False), ("", False), ("http://x", True)])
def test_enabled_only_with_access_url(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("ACCESS_URL", raising=False)
    else:
        monkeypatch.setenv("ACCESS_URL", value)
    assert client.enabled() is expected


def test_the_hub_answers_503_never_500():
    app = Flask(__name__)
    client.init_app(app)

    @app.get("/boom")
    def boom():
        raise client.AccessUnavailable("GET /bookings/1/access: 503")

    response = app.test_client().get("/boom")
    assert response.status_code == 503
    assert response.get_json() == {"error": "access unavailable"}
