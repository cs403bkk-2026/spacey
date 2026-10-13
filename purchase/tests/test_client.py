"""The Purchase client against a stub: a stand-in for the Purchase service.

The examples below are copied from openapi.yaml of cs403bkk-2026/spacey-purchase
at commit cccf50b. Each booking carries an extra "status", which the contract
does not have: the tests prove that the client drops it.
"""

import json
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from purchase import client

TOKEN = "test-token"

BOOKING = {
    "id": 1,
    "space_id": 1,
    "member": "annabel",
    "paid": False,
    "start_time": "2030-01-01T10:00:00+00:00",
    "end_time": "2030-01-01T11:00:00+00:00",
    "amount_cents": 2500,
    "user_id": 1,
    "card_last4": None,
    "created_at": "2026-10-12T02:48:20.933270+00:00",
    "status": "completed",
}
SPACE = {"id": 1, "name": "Founders Desk", "capacity": 1, "price_cents": 2500}


def closed_port_url() -> str:
    """A URL on a local port that nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


class Stub:
    """Records each request and answers each (method, path) from `answers`."""

    def __init__(self):
        self.requests = []
        self.answers = {}  # (method, path) -> (status, body); body: JSON, str or None
        self.url = ""

    def answer(self, method, path, status, body=None):
        self.answers[(method, path)] = (status, body)


@pytest.fixture
def stub(monkeypatch):
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def handle_any(self):
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            state.requests.append({
                "method": self.command,
                "path": parts.path,
                "query": parse_qs(parts.query),
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "body": json.loads(raw) if raw else None,
            })
            default = (204, None) if parts.path == "/test/reset" else (404, "no answer")
            status, body = state.answers.get((self.command, parts.path), default)
            if body is None:
                payload, content_type = b"", "application/json"
            elif isinstance(body, str):
                payload, content_type = body.encode(), "text/plain"
            else:
                payload, content_type = json.dumps(body).encode(), "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = do_DELETE = handle_any

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    monkeypatch.setenv("PURCHASE_URL", state.url)
    monkeypatch.setenv("PURCHASE_TOKEN", TOKEN)
    yield state
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("url,expected", [
    (None, False), ("", False), ("http://purchase:8000", True),
], ids=["unset", "empty", "set"])
def test_url_switch(monkeypatch, url, expected):
    if url is None:
        monkeypatch.delenv("PURCHASE_URL", raising=False)
    else:
        monkeypatch.setenv("PURCHASE_URL", url)

    assert client.enabled() is expected


def test_call_sends_token_and_json(stub):
    stub.answer("POST", "/spaces", 201, SPACE)

    client.create_space("Desk", 2, 1500)

    assert stub.requests == [{
        "method": "POST",
        "path": "/spaces",
        "query": {},
        "authorization": f"Bearer {TOKEN}",
        "content_type": "application/json",
        "body": {"name": "Desk", "capacity": 2, "price_cents": 1500},
    }]


START = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
END = datetime(2030, 1, 1, 11, tzinfo=timezone.utc)
# What the old SQL returns for BOOKING: only the old columns, times as datetime.
OLD_BOOKING = {
    "id": 1, "space_id": 1, "member": "annabel", "paid": False,
    "start_time": START, "end_time": END, "amount_cents": 2500, "user_id": 1,
    "card_last4": None,
    "created_at": datetime(2026, 10, 12, 2, 48, 20, 933270, tzinfo=timezone.utc),
}
USER = {"id": 1, "email": "annabel@example.com"}
PAYABLE = {"id": 1, "amount_cents": 2500, "status": "pending"}
METRICS = {
    "spaces": 1, "bookings": 2, "paid_bookings": 1, "unpaid_bookings": 1,
    "members": 1, "revenue_cents": 2500, "utilization": 0.01,
    "repeat_member_rate": 1, "payment_conversion": 0.5,
    "avg_revenue_cents_per_paid_booking": 2500,
    "revenue_by_space": [{"id": 1, "name": "Founders Desk", "revenue_cents": 2500}],
}
NEW_SPACE = {"id": 2, "name": "Meeting Room A", "capacity": 6, "price_cents": 1500}
SPACE_LIST = {"spaces": [{**SPACE, "available": True}]}
BOOKINGS = {"bookings": [BOOKING]}

# (function, args, method, path, status, payload, what the old body returns)
SUCCESS = [
    ("list_spaces", (), "GET", "/spaces", 200, SPACE_LIST, [SPACE]),
    ("get_space", (1,), "GET", "/spaces/1", 200, {**SPACE, "available": True}, SPACE),
    ("booked_space_ids", (None,), "GET", "/spaces/booked-ids", 200,
     {"space_ids": [1, 3]}, {1, 3}),
    ("create_space", ("Meeting Room A", 6, 1500), "POST", "/spaces", 201, NEW_SPACE,
     (NEW_SPACE, 201)),
    ("update_space", (1, {"price_cents": 2000}), "PATCH", "/spaces/1", 200,
     {**SPACE, "price_cents": 2000}, ({**SPACE, "price_cents": 2000}, 200)),
    ("delete_space", (1,), "DELETE", "/spaces/1", 204, None, (None, 204)),
    ("register_user", ("annabel@example.com", "hunter22"), "POST", "/register",
     201, USER, (USER, 201)),
    ("authenticate", ("annabel@example.com", "hunter22"), "POST",
     "/users/authenticate", 200, USER, (USER, 200)),
    ("create_booking", (1, "annabel", START, END, 1, 1), "POST",
     "/spaces/1/bookings", 201, BOOKING, (OLD_BOOKING, 201)),
    ("list_bookings", (), "GET", "/bookings", 200, BOOKINGS, [OLD_BOOKING]),
    ("list_space_bookings", (1,), "GET", "/spaces/1/bookings", 200, BOOKINGS,
     [OLD_BOOKING]),
    ("list_user_bookings", (1,), "GET", "/users/1/bookings", 200, BOOKINGS,
     [OLD_BOOKING]),
    ("get_booking", (1,), "GET", "/bookings/1", 200, BOOKING, OLD_BOOKING),
    ("check_payable", (1,), "GET", "/bookings/1/payable", 200, PAYABLE,
     (PAYABLE, 200)),
    ("check_unlockable", (1,), "GET", "/bookings/1/unlockable", 204, None, None),
    ("mark_paid", (1, "4242"), "POST", "/bookings/1/paid", 200, BOOKING,
     OLD_BOOKING),
    ("cancel_booking", (1,), "DELETE", "/bookings/1", 200, BOOKING, OLD_BOOKING),
    ("compute_metrics", (), "GET", "/metrics", 200, METRICS, METRICS),
]


@pytest.mark.parametrize(
    "name,args,method,path,status,payload,expected",
    SUCCESS, ids=[case[0] for case in SUCCESS],
)
def test_local_shapes(stub, name, args, method, path, status, payload, expected):
    stub.answer(method, path, status, payload)

    result = getattr(client, name)(*args)

    assert result == expected
    assert type(result) is type(expected)
    assert [(r["method"], r["path"]) for r in stub.requests] == [(method, path)]


def err(message):
    return {"error": message}


# (function, args, method, path, status, answer); the answer is a JSON error.
FAILURES = [
    ("get_space", (1,), "GET", "/spaces/1", 404, err("space not found")),
    ("get_booking", (1,), "GET", "/bookings/1", 404, err("booking not found")),
    ("mark_paid", (1, "4242"), "POST", "/bookings/1/paid", 404,
     err("booking not found")),
    ("mark_paid", (1, "4242"), "POST", "/bookings/1/paid", 409,
     err("booking hold has expired")),
    ("cancel_booking", (1,), "DELETE", "/bookings/1", 404, err("booking not found")),
    ("create_space", ("", 1, 0), "POST", "/spaces", 400, err("name and capacity are required")),
    ("update_space", (1, {}), "PATCH", "/spaces/1", 400, err("provide name, capacity and/or price_cents to update")),
    ("update_space", (1, {"name": "x"}), "PATCH", "/spaces/1", 404,
     err("space not found")),
    ("delete_space", (1,), "DELETE", "/spaces/1", 404, err("space not found")),
    ("delete_space", (1,), "DELETE", "/spaces/1", 409,
     err("space has bookings, cancel them first")),
    ("register_user", ("x", "y"), "POST", "/register", 400,
     err("enter a valid email address")),
    ("register_user", ("a@b.co", "hunter22"), "POST", "/register", 409,
     err("email is already registered")),
    ("authenticate", ("a@b.co", "no"), "POST", "/users/authenticate", 401,
     err("invalid email or password")),
    ("create_booking", (1, "a", START, END, 0, None), "POST", "/spaces/1/bookings",
     400, err("start_time and end_time are required (ISO 8601 with timezone)")),
    ("create_booking", (9, "a", START, END, 1, None), "POST", "/spaces/9/bookings",
     404, err("space not found")),
    ("create_booking", (1, "a", START, END, 1, None), "POST", "/spaces/1/bookings",
     409, err("space is already booked for that time")),
    ("check_payable", (1,), "GET", "/bookings/1/payable", 404,
     err("booking not found")),
    ("check_payable", (1,), "GET", "/bookings/1/payable", 409,
     err("booking hold has expired")),
    ("check_unlockable", (1,), "GET", "/bookings/1/unlockable", 402,
     err("booking is not paid")),
    ("check_unlockable", (1,), "GET", "/bookings/1/unlockable", 404,
     err("booking not found")),
]
# Where the old body gives None instead of (payload, status).
NONE_ON_ERROR = {"get_space", "get_booking", "mark_paid", "cancel_booking"}


@pytest.mark.parametrize(
    "name,args,method,path,status,answer",
    FAILURES, ids=[f"{case[0]}-{case[4]}" for case in FAILURES],
)
def test_not_found_and_domain_errors(stub, name, args, method, path, status, answer):
    stub.answer(method, path, status, answer)

    result = getattr(client, name)(*args)

    assert result == (None if name in NONE_ON_ERROR else (answer, status))


def answered(status, body):
    return lambda stub, monkeypatch: stub.answer("GET", "/bookings/1", status, body)


def pointed_at(url):
    return lambda stub, monkeypatch: monkeypatch.setenv("PURCHASE_URL", url())


LINK_FAILURES = {
    "401": answered(401, err("invalid service token")),
    "403": answered(403, err("invalid service token")),
    "500": answered(500, err("boom")),
    "text-502": answered(502, "Bad Gateway"),
    "text-404": answered(404, "Not Found"),  # a missing route, not a missing booking
    "200-empty": answered(200, {}),
    "closed-port": pointed_at(closed_port_url),
    "no-scheme": pointed_at(lambda: "spacey-purchase:8000"),
    "no-value": pointed_at(lambda: "<no value>"),
}


@pytest.mark.parametrize("break_link", LINK_FAILURES.values(), ids=LINK_FAILURES)
def test_link_failures_raise(stub, monkeypatch, break_link):
    break_link(stub, monkeypatch)

    with pytest.raises(client.PurchaseUnavailable):
        client.get_booking(1)


MALFORMED = {
    "ids-not-a-list": ("booked_space_ids", (None,), "/spaces/booked-ids", {"space_ids": 5}),
    "ids-unhashable": ("booked_space_ids", (None,), "/spaces/booked-ids", {"space_ids": [[1]]}),
    "list-not-a-list": ("list_bookings", (), "/bookings", {"bookings": "x"}),
    "metrics-not-an-object": ("compute_metrics", (), "/metrics", []),
    "bad-time": ("get_booking", (1,), "/bookings/1", {**BOOKING, "created_at": "soon"}),
}


@pytest.mark.parametrize("name,args,path,payload", MALFORMED.values(), ids=MALFORMED)
def test_malformed_answers_raise(stub, name, args, path, payload):
    stub.answer("GET", path, 200, payload)

    with pytest.raises(client.PurchaseUnavailable):
        getattr(client, name)(*args)


def test_timeout_no_retry(monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    accepted = []

    def hold():  # accept and never answer
        while True:
            try:
                accepted.append(listener.accept()[0])
            except OSError:
                return

    threading.Thread(target=hold, daemon=True).start()
    monkeypatch.setenv("PURCHASE_URL", f"http://127.0.0.1:{listener.getsockname()[1]}")
    started = time.monotonic()

    with pytest.raises(client.PurchaseUnavailable):
        client.cancel_booking(1)

    elapsed = time.monotonic() - started
    time.sleep(0.2)  # a retry would connect again within this time
    listener.close()
    for connection in accepted:
        connection.close()
    assert elapsed < 2
    assert len(accepted) == 1


def test_raw_values_sent(stub):
    window = (
        datetime.fromisoformat("2030-01-01T10:00:00+07:00"),
        datetime.fromisoformat("2030-01-01T12:00:00+07:00"),
    )
    stub.answer("GET", "/spaces/booked-ids", 200, {"space_ids": []})
    stub.answer("PATCH", "/spaces/1", 400, err("name and capacity are required"))
    stub.answer("POST", "/spaces/1/bookings", 400, err("member must be a string"))

    client.booked_space_ids(window)
    client.update_space(1, {"name": None})
    client.create_booking(1, 5, window[0], window[1], True, None)

    ids, update, create = stub.requests
    assert ids["query"] == {
        "start_time": ["2030-01-01T10:00:00+07:00"],
        "end_time": ["2030-01-01T12:00:00+07:00"],
    }
    assert update["body"] == {"name": None}
    assert create["body"] == {
        "member": 5, "start_time": "2030-01-01T10:00:00+07:00",
        "end_time": "2030-01-01T12:00:00+07:00", "party_size": True,
        "user_id": None,
    }


def test_503_without_secrets(stub, monkeypatch):
    stub.answer("POST", "/register", 500, err("boom"))
    logged = []
    monkeypatch.setattr(
        client.logger, "warning", lambda message, *args: logged.append(message % args)
    )
    app = create_app(reset_on_start=True)

    @app.post("/register-probe")
    def probe():
        client.register_user("annabel@example.com", "hunter22-secret")

    response = app.test_client().post("/register-probe")

    assert (response.status_code, response.get_json()) == (
        503, {"error": "purchase unavailable"})
    assert any("POST /register: 500" in line for line in logged)
    assert not any("hunter22-secret" in line or TOKEN in line for line in logged)


FREEZE = """
CREATE FUNCTION frozen_for_test() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'frozen' USING ERRCODE = '25006'; END $$;
CREATE TRIGGER frozen_for_test BEFORE INSERT ON bookings
FOR EACH ROW EXECUTE FUNCTION frozen_for_test();
"""


def test_frozen_table_503(monkeypatch):
    monkeypatch.delenv("PURCHASE_URL", raising=False)
    app = create_app(reset_on_start=True)
    with app.db.cursor() as cur:
        cur.execute(FREEZE)
    try:
        response = app.test_client().post("/spaces/1/bookings", json={
            "start_time": "2030-01-01T10:00:00Z", "end_time": "2030-01-01T11:00:00Z"})
    finally:
        with app.db.cursor() as cur:
            cur.execute("DROP TRIGGER frozen_for_test ON bookings")
            cur.execute("DROP FUNCTION frozen_for_test()")

    assert (response.status_code, response.get_json()) == (
        503, {"error": "purchase unavailable"})
