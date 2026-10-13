from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from purchase.booking import calculate_booking_price_cents, check_unlockable
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
