"""PUR-025: the hub's own check of its link to the Purchase service."""

import pytest
from test_client import METRICS, stub  # noqa: F401 (stub is a fixture)

from purchase import client


@pytest.fixture
def logged(monkeypatch):
    lines = []
    for level in ("info", "warning"):
        monkeypatch.setattr(client.logger, level,
                            lambda msg, *args: lines.append(msg % args))
    return lines


@pytest.mark.parametrize("status,line", [
    (200, "purchase service check: ok"),
    (403, "purchase service check: failed (GET /metrics: 403)"),
])
def test_check_link_logs_the_answer(stub, logged, status, line):
    body = METRICS if status == 200 else {"error": "invalid service token"}
    stub.answer("GET", "/metrics", status, body)

    client.check_link()

    assert logged == [line]
    assert stub.requests[0]["authorization"].startswith("Bearer ")


def test_check_link_never_raises(stub, logged, monkeypatch):
    def broken():
        raise RuntimeError("secret detail")
    monkeypatch.setattr(client, "compute_metrics", broken)

    client.check_link()

    assert logged == ["purchase service check: failed (RuntimeError)"]


def test_check_link_without_url_calls_nothing(monkeypatch, logged):
    monkeypatch.delenv("PURCHASE_URL", raising=False)

    client.check_link()

    assert logged == []
