from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import purchase.booking
from app import create_app
from purchase.booking import (
    calculate_booking_price_cents,
    check_payable,
    check_unlockable,
)
from purchase.member import is_valid_email, is_valid_password

# A mocked, obviously-fake card - always valid, never a real payment.
VALID_CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}


def book_through_the_api():
    """A fresh app and an unpaid booking made through POST /spaces/1/bookings."""
    app = create_app(reset_on_start=True)
    client = app.test_client()
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    booking = client.post(
        "/spaces/1/bookings",
        json={
            "member": "annabel",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=1)).isoformat(),
        },
    ).get_json()
    return app, client, booking


@pytest.mark.parametrize(
    "hourly_rate_cents,seconds,expected_cents",
    [
        (1500, 1800, 750),
        (1000, 1200, 333),
        (100, 18, 1),
        (100, 17, 0),
        (3600, 1.9, 1),
        (0, 3600, 0),
    ],
)
def test_booking_price_examples(hourly_rate_cents, seconds, expected_cents):
    start = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert calculate_booking_price_cents(
        hourly_rate_cents, start, start + timedelta(seconds=seconds)
    ) == expected_cents


@pytest.mark.parametrize(
    "email,expected",
    [
        ("member@example.com", True),
        ("  member@example.com  ", True),
        ("member@example", False),
        ("member example@example.com", False),
        ("", False),
        (None, False),
        (42, False),
    ],
)
def test_email_validation_examples(email, expected):
    assert is_valid_email(email) is expected


@pytest.mark.parametrize(
    "password,expected",
    [
        ("12345678", True),
        ("1234567", False),
        ("", False),
        (None, False),
        (12345678, False),
    ],
)
def test_password_validation_examples(password, expected):
    assert is_valid_password(password) is expected


@pytest.mark.parametrize("cancelled", [False, True], ids=["unknown_id", "cancelled"])
def test_check_unlockable_missing_booking_is_404(cancelled):
    app, client, booking = book_through_the_api()
    booking_id = booking["id"] if cancelled else 999
    if cancelled:
        client.delete(f"/bookings/{booking_id}")

    with app.db.cursor() as cur:
        answer = check_unlockable(cur, booking_id)

    assert answer == ({"error": "booking not found"}, 404)


def test_check_unlockable_unpaid_booking_is_402():
    app, _, booking = book_through_the_api()

    with app.db.cursor() as cur:
        answer = check_unlockable(cur, booking["id"])

    assert answer == ({"error": "booking is not paid"}, 402)


def test_check_unlockable_paid_booking_is_allowed():
    app, client, booking = book_through_the_api()
    client.post(f"/bookings/{booking['id']}/pay", json=VALID_CARD)

    with app.db.cursor() as cur:
        answer = check_unlockable(cur, booking["id"])

    assert answer is None


def test_check_payable_unpaid_booking_is_pending():
    app, _, booking = book_through_the_api()

    with app.db.cursor() as cur:
        result = check_payable(cur, booking["id"])

    assert result == (
        {
            "id": booking["id"],
            "amount_cents": booking["amount_cents"],
            "status": "pending",
        },
        200,
    )


def test_check_payable_paid_booking_is_completed():
    app, client, booking = book_through_the_api()
    client.post(f"/bookings/{booking['id']}/pay", json=VALID_CARD)

    with app.db.cursor() as cur:
        result = check_payable(cur, booking["id"])

    assert result == (
        {
            "id": booking["id"],
            "amount_cents": booking["amount_cents"],
            "status": "completed",
        },
        200,
    )


def an_unknown_id(client, booking):
    return booking["id"] + 999


def a_cancelled_id(client, booking):
    client.delete(f"/bookings/{booking['id']}")
    return booking["id"]


@pytest.mark.parametrize(
    "missing_id", [an_unknown_id, a_cancelled_id], ids=["unknown_id", "cancelled"]
)
def test_check_payable_missing_booking_is_404(missing_id):
    app, client, booking = book_through_the_api()
    booking_id = missing_id(client, booking)

    with app.db.cursor() as cur:
        result = check_payable(cur, booking_id)

    assert result == ({"error": "booking not found"}, 404)


def test_confirmation_pay_route_is_gone():
    _, client, booking = book_through_the_api()

    response = client.post(
        f"/bookings/{booking['id']}/confirmation/pay", data=VALID_CARD
    )

    assert response.status_code == 404
    assert client.get(f"/bookings/{booking['id']}").get_json()["paid"] is False


UNPAID = {"id": 1, "paid": False, "card_last4": None, "amount_cents": 2500}
PAID = {"id": 1, "paid": True, "card_last4": "4242"}
PENDING = ({"id": 1, "amount_cents": 2500, "status": "pending"}, 200)
HOLD_EXPIRED = ({"error": "booking hold has expired"}, 409)
NOT_FOUND = ({"error": "booking not found"}, 404)
REFUND = {"db": "app.db", "booking_id": 1, "amount_cents": 2500,
          "card_last4": "4242", "reason": "hold_expired"}
# Stands in for the cursor: the refund goes to its connection.
CURSOR = SimpleNamespace(connection="app.db")


def pay(monkeypatch, booking=UNPAID, payable=(PENDING,), paid_row=PAID,
        url="http://purchase.test"):
    """Run mark_booking_paid with every step stubbed. check_payable gives the
    `payable` answers in order. Returns (answer, number of calls per step)."""
    calls = {"check_payable": 0, "charge": 0, "mark_paid": 0}
    answers = iter(payable)

    def check_payable(cur, booking_id):
        calls["check_payable"] += 1
        return next(answers)

    def authorize_card(*args):
        calls["charge"] += 1  # returns None: the card is accepted

    def mark_paid(cur, booking_id, card_last4):
        calls["mark_paid"] += 1
        return paid_row

    def refund_payment(db, **refund):
        # Only a refund adds this key, so each `calls ==` check also proves none ran.
        calls.setdefault("refunds", []).append({"db": db, **refund})

    if url is None:
        monkeypatch.delenv("PURCHASE_URL", raising=False)
    else:
        monkeypatch.setenv("PURCHASE_URL", url)
    monkeypatch.setattr(purchase.booking, "get_booking", lambda cur, i: booking)
    monkeypatch.setattr(purchase.booking, "check_payable", check_payable)
    monkeypatch.setattr(purchase.booking, "authorize_card", authorize_card)
    monkeypatch.setattr(purchase.booking, "mark_paid", mark_paid)
    monkeypatch.setattr(purchase.booking, "refund_payment", refund_payment)
    answer = purchase.booking.mark_booking_paid(
        CURSOR, 1, "4242424242424242", "12/99", "123"
    )
    return answer, calls


@pytest.mark.parametrize(
    ("payable", "expected", "charges"),
    [
        (HOLD_EXPIRED, HOLD_EXPIRED, 0),
        (NOT_FOUND, NOT_FOUND, 0),
        (PENDING, (PAID, 200), 1),
    ],
    ids=["expired", "cancelled_since", "pending"],
)
def test_pay_checks_the_hold_before_the_card(monkeypatch, payable, expected, charges):
    answer, calls = pay(monkeypatch, payable=(payable,))

    assert answer == expected
    assert calls == {"check_payable": 1, "charge": charges, "mark_paid": charges}


@pytest.mark.parametrize(
    ("booking", "expected"),
    [(PAID, (PAID, 200)), (None, NOT_FOUND)],
    ids=["already_paid", "unknown"],
)
def test_pay_answers_paid_or_unknown_before_the_check(monkeypatch, booking, expected):
    answer, calls = pay(monkeypatch, booking=booking)

    assert answer == expected
    assert calls == {"check_payable": 0, "charge": 0, "mark_paid": 0}


def test_pay_refused_after_the_charge_is_409(monkeypatch):
    answer, calls = pay(monkeypatch, payable=(PENDING, HOLD_EXPIRED), paid_row=None)

    assert answer == HOLD_EXPIRED
    assert calls == {"check_payable": 2, "charge": 1, "mark_paid": 1,
                     "refunds": [REFUND]}


@pytest.mark.parametrize(
    ("amount_cents", "refusal", "refunds"),
    [(2500, NOT_FOUND, [REFUND]), (0, HOLD_EXPIRED, None)],
    ids=["cancelled_since", "free"],
)
def test_pay_refusal_refunds_what_was_charged(monkeypatch, amount_cents, refusal, refunds):
    booking = {**UNPAID, "amount_cents": amount_cents}
    answer, calls = pay(
        monkeypatch, booking=booking, payable=(PENDING, refusal), paid_row=None)

    assert answer == refusal
    assert calls.get("refunds") == refunds


@pytest.mark.parametrize(
    ("url", "paid_row"),
    [(None, PAID), ("", PAID), (None, None)],
    ids=["unset", "empty", "unset_row_gone"],
)
def test_pay_without_purchase_url_is_unchanged(monkeypatch, url, paid_row):
    answer, calls = pay(monkeypatch, payable=(), paid_row=paid_row, url=url)

    assert answer == (paid_row, 200)
    assert calls == {"check_payable": 0, "charge": 1, "mark_paid": 1}
