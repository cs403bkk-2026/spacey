"""The hub's routes with PURCHASE_URL on the stub service (see test_client)."""

from datetime import datetime, timedelta, timezone

import pytest
from test_client import (  # noqa: F401  (stub is a fixture)
    BOOKING, METRICS, PAYABLE, SPACE, SPACE_LIST, SUCCESS, TOKEN, USER,
    closed_port_url, err, stub,
)

import purchase.booking
import purchase.member
import purchase.metrics
import purchase.space
from app import create_app
from purchase import client

# A mocked, obviously-fake card - always valid, never a real payment.
VALID_CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}

MODULES = {
    **dict.fromkeys(
        ["list_spaces", "get_space", "booked_space_ids", "create_space",
         "update_space", "delete_space"], purchase.space),
    **dict.fromkeys(["register_user", "authenticate"], purchase.member),
    "compute_metrics": purchase.metrics,
}
PAID = {**BOOKING, "paid": True, "card_last4": "4242"}


@pytest.fixture
def hub(stub):
    """The hub's test client, with PURCHASE_URL on the stub."""
    return create_app(reset_on_start=True).test_client()


def test_routes_answer_as_before(stub, hub):
    stub.answer("GET", "/bookings/1", 200, {
        **BOOKING,
        "start_time": "2030-01-01T17:00:00+07:00",
        "end_time": "2030-01-01T18:00:00+07:00",
    })
    stub.answer("GET", "/spaces", 200, SPACE_LIST)
    stub.answer("GET", "/spaces/booked-ids", 200, {"space_ids": [1]})
    stub.answer("GET", "/metrics", 200, METRICS)

    booking = hub.get("/bookings/1").get_json()
    spaces = hub.get("/spaces").get_json()
    metrics = hub.get("/metrics").get_json()

    assert booking == {
        "id": 1, "space_id": 1, "member": "annabel", "paid": False,
        "start_time": "2030-01-01T10:00:00+00:00",
        "end_time": "2030-01-01T11:00:00+00:00",
        "amount_cents": 2500, "user_id": 1, "card_last4": None,
        "created_at": "2026-10-12T02:48:20.933270+00:00",
    }
    assert spaces == {"spaces": [{**SPACE, "available": False}]}
    assert metrics == METRICS


@pytest.mark.parametrize(
    "name,args,method,path,status,payload,expected",
    SUCCESS, ids=[case[0] for case in SUCCESS],
)
def test_cur_unused(stub, name, args, method, path, status, payload, expected):
    stub.answer(method, path, status, payload)
    module = MODULES.get(name, purchase.booking)

    result = getattr(module, name)(None, *args)

    assert result == expected
    assert [(r["method"], r["path"]) for r in stub.requests] == [(method, path)]


def test_cancel_still_refunds(stub, hub, monkeypatch):
    stub.answer("DELETE", "/bookings/1", 200, {**PAID, "amount_cents": 2500})
    refunds = []
    monkeypatch.setattr(
        "app.refund_payment", lambda conn, **kwargs: refunds.append(kwargs)
    )

    response = hub.delete("/bookings/1")

    assert response.status_code == 200
    assert refunds == [{
        "booking_id": 1, "amount_cents": 2500, "card_last4": "4242",
        "reason": "cancellation",
    }]


@pytest.mark.parametrize("status,answer,expected,user_id", [
    (401, err("invalid email or password"), 401, None),
    (200, {**USER, "id": 7}, 200, 7),
    (403, err("invalid service token"), 503, None),
], ids=["401", "200", "403"])
def test_login(stub, hub, status, answer, expected, user_id):
    stub.answer("POST", "/users/authenticate", status, answer)

    response = hub.post("/login", json={"email": "a@b.co", "password": "hunter22"})

    assert response.status_code == expected
    with hub.session_transaction() as session:
        assert session.get("user_id") == user_id


def test_link_down(stub, hub, monkeypatch):
    monkeypatch.setenv("PURCHASE_URL", closed_port_url())
    with hub.session_transaction() as session:
        session["user_id"] = 1
    window = {
        "start_time": "2030-01-01T10:00:00Z", "end_time": "2030-01-01T11:00:00Z"}
    routes = [
        ("post", "/register", {"email": "a@b.co", "password": "hunter22"}),
        ("post", "/login", {"email": "a@b.co", "password": "hunter22"}),
        ("get", "/spaces", None),
        ("post", "/spaces", {"name": "Desk", "capacity": 1}),
        ("get", "/spaces/1", None),
        ("patch", "/spaces/1", {"name": "Desk"}),
        ("delete", "/spaces/1", None),
        ("get", "/spaces/1/bookings", None),
        ("post", "/spaces/1/bookings", window),
        ("get", "/bookings", None),
        ("get", "/bookings/1", None),
        ("delete", "/bookings/1", None),
        ("get", "/me/bookings", None),
        ("post", "/bookings/1/pay", VALID_CARD),
        ("post", "/bookings/1/unlock", None),
        ("get", "/metrics", None),
    ]

    answers = [
        (method, path, getattr(hub, method)(path, json=body))
        for method, path, body in routes
    ]

    for method, path, response in answers:
        assert (method, path, response.status_code, response.get_json()) == (
            method, path, 503, {"error": "purchase unavailable"})
    assert hub.get("/health").status_code == 200


def test_reset_hook(stub, monkeypatch):
    create_app(reset_on_start=True)

    assert [(r["method"], r["path"], r["authorization"]) for r in stub.requests] == [
        ("POST", "/test/reset", f"Bearer {TOKEN}")]

    stub.answer("POST", "/test/reset", 404, "Not Found")
    with pytest.raises(client.PurchaseUnavailable):
        create_app(reset_on_start=True)

    stub.requests.clear()
    monkeypatch.delenv("PURCHASE_URL")
    create_app(reset_on_start=True)
    assert stub.requests == []


@pytest.mark.parametrize("payable,paid_booking,stored,status,body,charges,paid_calls", [
    ((409, err("booking hold has expired")), None, BOOKING,
     409, err("booking hold has expired"), 0, 0),
    ((404, err("booking not found")), None, BOOKING,
     404, err("booking not found"), 0, 0),
    ((200, PAYABLE), PAID, BOOKING, 200, None, 1, 1),
    (None, None, PAID, 200, None, 0, 0),
], ids=["expired", "cancelled_since", "pending", "already_paid"])
def test_pay_checks_the_hold_first(
    stub, hub, monkeypatch, payable, paid_booking, stored, status, body,
    charges, paid_calls,
):
    stub.answer("GET", "/bookings/1", 200, stored)
    if payable:
        stub.answer("GET", "/bookings/1/payable", *payable)
    if paid_booking:
        stub.answer("POST", "/bookings/1/paid", 200, paid_booking)
    charged = []
    monkeypatch.setattr(
        "purchase.booking.authorize_card", lambda *args: charged.append(args)
    )

    response = hub.post("/bookings/1/pay", json=VALID_CARD)

    assert response.status_code == status
    if body is None:
        assert response.get_json()["paid"] is True
        assert response.get_json()["card_last4"] == "4242"
    else:
        assert response.get_json() == body
    assert len(charged) == charges
    assert len([r for r in stub.requests if r["path"] == "/bookings/1/paid"]) == paid_calls


def test_pay_unknown_booking_is_404(stub, hub, monkeypatch):
    stub.answer("GET", "/bookings/1", 404, err("booking not found"))
    charged = []
    monkeypatch.setattr(
        "purchase.booking.authorize_card", lambda *args: charged.append(args)
    )

    response = hub.post("/bookings/1/pay", json=VALID_CARD)

    assert (response.status_code, response.get_json()) == (
        404, err("booking not found"))
    assert charged == []


def test_pay_refused_after_the_charge_is_409(stub, hub, monkeypatch):
    stub.answer("GET", "/bookings/1", 200, BOOKING)
    stub.answer("GET", "/bookings/1/payable", 200, PAYABLE)

    def charge_then_expire(*args):  # the hold runs out while the card is charged
        stub.answer("GET", "/bookings/1/payable", 409, err("booking hold has expired"))
        stub.answer("POST", "/bookings/1/paid", 409, err("booking hold has expired"))

    monkeypatch.setattr("purchase.booking.authorize_card", charge_then_expire)

    response = hub.post("/bookings/1/pay", json=VALID_CARD)

    assert (response.status_code, response.get_json()) == (
        409, err("booking hold has expired"))
