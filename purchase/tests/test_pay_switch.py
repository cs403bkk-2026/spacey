"""PUR-027: /pay through the Purchase service while the switch row's pays is
true, on the stub service (see test_client). client.pays answers True unless
a test says otherwise."""

import time

import pytest
from test_client import (  # noqa: F401  (stub is a fixture)
    BOOKING, PAYABLE, TOKEN, closed_port_url, err, stub,
)

import purchase.booking
from app import create_app
from purchase import client

# A mocked, obviously-fake card - always valid, never a real payment.
CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}
PAID = {**BOOKING, "paid": True, "card_last4": "4242"}
PAID_JSON = {
    "id": 1, "space_id": 1, "member": "annabel", "paid": True,
    "start_time": "2030-01-01T10:00:00+00:00",
    "end_time": "2030-01-01T11:00:00+00:00",
    "amount_cents": 2500, "user_id": 1, "card_last4": "4242",
    "created_at": "2026-10-12T02:48:20.933270+00:00",
}


@pytest.fixture
def hub(stub, monkeypatch):
    """The hub's test client, with PURCHASE_URL on the stub and pays on."""
    monkeypatch.setattr(client, "pays", lambda: True)
    return create_app(reset_on_start=True).test_client()


@pytest.fixture
def seen(monkeypatch):
    """What the hub did itself: its local charge, mirror and refund."""
    calls = {"authorize_card": [], "mirror": [], "refund_payment": []}
    monkeypatch.setattr(purchase.booking, "authorize_card",
                        lambda *args: calls["authorize_card"].append(args))
    monkeypatch.setattr(purchase.booking.mirror, "booking",
                        lambda row: calls["mirror"].append(row))
    monkeypatch.setattr("app.refund_payment",
                        lambda conn, **kwargs: calls["refund_payment"].append(kwargs))
    return calls


class SlowAnswers(dict):
    """The stub's answers, with one (method, path) answered after 3 s."""

    def __init__(self, answers, slow):
        super().__init__(answers)
        self.slow = slow

    def get(self, key, default=None):
        if key == self.slow:
            time.sleep(3)
        return super().get(key, default)


@pytest.mark.parametrize("status,answer,expected", [
    (200, PAID, (200, PAID_JSON)),
    (400, err("card_number is not a valid card number"),
     (400, err("card_number is not a valid card number"))),
    (402, err("payment failed"), (402, err("payment failed"))),
    (404, err("booking not found"), (404, err("booking not found"))),
    (409, err("booking hold has expired"), (409, err("booking hold has expired"))),
    (503, err("payment unavailable"), (503, err("payment unavailable"))),
    (500, "Internal Server Error", (503, err("purchase unavailable"))),
    (None, None, (503, err("purchase unavailable"))),
], ids=["200", "400", "402", "404", "409", "503", "text_500", "closed_port"])
def test_pay_goes_to_the_service(stub, hub, seen, monkeypatch, status, answer, expected):
    if status is None:
        monkeypatch.setenv("PURCHASE_URL", closed_port_url())
    else:
        stub.answer("POST", "/bookings/1/pay", status, answer)

    response = hub.post("/bookings/1/pay", json={**CARD, "force_failure": True})

    assert (response.status_code, response.get_json()) == expected
    sent = [r for r in stub.requests if r["path"] == "/bookings/1/pay"]
    if status is not None:
        assert [r["body"] for r in sent] == [{**CARD, "force_failure": True}]
        assert sent[0]["authorization"] == f"Bearer {TOKEN}"
    assert seen["authorize_card"] == []
    assert len(seen["mirror"]) == (1 if status == 200 else 0)


@pytest.mark.parametrize("case", ["pay", "cancel", "paid"])
def test_slow_service(stub, hub, seen, monkeypatch, case):
    if case == "pay":
        slow = ("POST", "/bookings/1/pay")
        stub.answer(*slow, 200, PAID)
    elif case == "cancel":
        slow = ("DELETE", "/bookings/1")
        stub.answer("GET", "/bookings/1/cancellable", 204)
        stub.answer(*slow, 200, {**PAID, "refund": "refunded"})
    else:  # the flag off: the hub charges, the service's /paid is slow
        monkeypatch.setattr(client, "pays", lambda: False)
        slow = ("POST", "/bookings/1/paid")
        stub.answer("GET", "/bookings/1", 200, BOOKING)
        stub.answer("GET", "/bookings/1/payable", 200, PAYABLE)
        stub.answer(*slow, 200, PAID)
    stub.answers = SlowAnswers(stub.answers, slow)

    if case == "cancel":
        response = hub.delete("/bookings/1")
    else:
        response = hub.post("/bookings/1/pay", json=CARD)

    assert response.status_code == 200
    assert response.get_json()["paid"] is True


@pytest.mark.parametrize("case", ["url_unset", "row_false"])
def test_flag_off_keeps_the_local_path(stub, monkeypatch, seen, case):
    monkeypatch.setattr(purchase.booking, "authorize_card", lambda *args: (
        seen["authorize_card"].append(args) or (err("payment failed"), 402)))
    hub = create_app(reset_on_start=True).test_client()  # client.pays as it is
    if case == "url_unset":
        monkeypatch.delenv("PURCHASE_URL")
        monkeypatch.setattr(purchase.booking, "get_booking",
                            lambda cur, booking_id: BOOKING)
    else:
        stub.answer("GET", "/bookings/1", 200, BOOKING)
        stub.answer("GET", "/bookings/1/payable", 200, PAYABLE)

    response = hub.post("/bookings/1/pay", json=CARD)

    assert (response.status_code, response.get_json()) == (402, err("payment failed"))
    assert len(seen["authorize_card"]) == 1
    assert [r for r in stub.requests if r["path"] == "/bookings/1/pay"] == []


@pytest.mark.parametrize("case,expected", [("default", False), ("true", True)])
def test_pays_reads_the_switch_row(stub, case, expected):
    app = create_app(reset_on_start=True)
    try:
        if case == "true":
            with app.db.cursor() as cur:
                cur.execute("UPDATE purchase_switch SET pays = true")

        with app.app_context():
            assert client.pays() is expected
    finally:
        with app.db.cursor() as cur:
            cur.execute("UPDATE purchase_switch SET pays = false")


@pytest.mark.parametrize("refund,local_refunds", [
    ("refunded", 0), ("no_charge", 1), ("unavailable", 0), (None, 1),
], ids=["refunded", "no_charge", "unavailable", "no_key"])
def test_cancel_refunds_old_charges_locally(stub, hub, seen, refund, local_refunds):
    row = PAID if refund is None else {**PAID, "refund": refund}
    stub.answer("GET", "/bookings/1/cancellable", 204)
    stub.answer("DELETE", "/bookings/1", 200, row)

    response = hub.delete("/bookings/1")

    assert (response.status_code, response.get_json()) == (200, PAID_JSON)
    assert seen["refund_payment"] == [{
        "booking_id": 1, "amount_cents": 2500, "card_last4": "4242",
        "reason": "cancellation",
    }] * local_refunds
