"""PUR-026: spacey keeps no Purchase SQL. Every Purchase call goes to the
service; with PURCHASE_URL unset, every Purchase route answers 503. Only the
mirror still writes the old tables."""

import re

import psycopg
import pytest

import purchase.booking
from app import create_app
from purchase import mirror
from purchase.client import PurchaseUnavailable

VALID_CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}
WINDOW = {"start_time": "2031-06-01T10:00:00Z", "end_time": "2031-06-01T11:00:00Z"}
ACCOUNT = {"email": "service-only@example.test", "password": "hunter22"}
OLD_TABLES = re.compile(r"\b(users|spaces|bookings|subscriptions)\b", re.IGNORECASE)

PURCHASE_ROUTES = [
    ("GET", "/spaces", None),
    ("POST", "/spaces", {"name": "Desk", "capacity": 2}),
    ("GET", "/spaces/1", None),
    ("PATCH", "/spaces/1", {"name": "Desk 2"}),
    ("DELETE", "/spaces/1", None),
    ("GET", "/spaces/1/bookings", None),
    ("POST", "/spaces/1/bookings", WINDOW),
    ("GET", "/bookings", None),
    ("GET", "/bookings/1", None),
    ("DELETE", "/bookings/1", None),
    ("POST", "/bookings/1/pay", VALID_CARD),
    ("POST", "/bookings/1/unlock", None),
    ("GET", "/me/bookings", None),
    ("POST", "/register", ACCOUNT),
    ("POST", "/login", ACCOUNT),
    ("GET", "/metrics", None),
]


@pytest.mark.parametrize("url", [None, ""], ids=["unset", "empty"])
def test_unset_url_answers_503_on_every_purchase_route(monkeypatch, url):
    monkeypatch.delenv("PURCHASE_URL", raising=False)
    if url is not None:
        monkeypatch.setenv("PURCHASE_URL", url)
    client = create_app(reset_on_start=True).test_client()
    with client.session_transaction() as session:
        session["user_id"] = 1  # /me/bookings needs a session

    for method, path, body in PURCHASE_ROUTES:
        response = client.open(path, method=method, json=body)

        assert (response.status_code, response.get_json()) == (
            503, {"error": "purchase unavailable"}), f"{method} {path}"


@pytest.mark.parametrize("call", [
    lambda: purchase.booking.get_booking(None, 1),
    lambda: purchase.booking.check_payable(None, 1),
    lambda: purchase.booking.mark_paid(None, 1, "4242"),
    lambda: purchase.booking.check_unlockable(None, 1),
], ids=["get_booking", "check_payable", "mark_paid", "check_unlockable"])
def test_functions_pay_and_unlock_call_raise_when_unset(monkeypatch, call):
    monkeypatch.delenv("PURCHASE_URL", raising=False)

    with pytest.raises(PurchaseUnavailable):
        call()  # never None, which /pay and /unlock would read as "fine"


def test_hub_routes_still_work_when_unset(monkeypatch):
    monkeypatch.delenv("PURCHASE_URL", raising=False)
    client = create_app(reset_on_start=True).test_client()

    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 302
    assert client.get("/dashboard").status_code == 302
    assert client.post("/logout").status_code == 200
    assert client.post("/members/annabel/subscribe").status_code == 410


def test_only_the_mirror_writes_the_old_tables(monkeypatch):
    """The URL is the compose service's, as CI and local runs set it."""
    client = create_app(reset_on_start=True).test_client()
    mirrored = []
    monkeypatch.setattr(mirror, "_write", lambda what, *statements: mirrored.append(what))
    statements = []
    execute = psycopg.Cursor.execute

    def spy(cursor, query, *args, **kwargs):
        statements.append(str(query))
        return execute(cursor, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", spy)

    registered = client.post("/register", json=ACCOUNT)
    created = client.post("/spaces", json={"name": "Desk", "capacity": 2})
    space_id = created.get_json()["id"]
    updated = client.patch(f"/spaces/{space_id}", json={"name": "Desk 2"})
    deleted = client.delete(f"/spaces/{space_id}")
    booked = client.post("/spaces/1/bookings", json=WINDOW)
    booking_id = booked.get_json()["id"]
    paid = client.post(f"/bookings/{booking_id}/pay", json=VALID_CARD)
    cancelled = client.delete(f"/bookings/{booking_id}")
    metrics = client.get("/metrics")

    assert [r.status_code for r in (registered, created, updated, deleted,
                                    booked, paid, cancelled, metrics)] == [
        201, 201, 200, 204, 201, 200, 200, 200]
    assert [s for s in statements if OLD_TABLES.search(s)] == []
    user_id = registered.get_json()["id"]
    assert mirrored == [
        f"user {user_id}",
        f"space {space_id}", f"space {space_id}", f"delete space {space_id}",
        f"booking {booking_id}", f"booking {booking_id}", f"cancel {booking_id}",
    ]
