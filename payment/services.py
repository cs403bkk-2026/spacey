"""Payment business rules: card validation and the (mocked) payment flow.
No Flask and no SQL - HTTP lives in api.py, the database in repository.py."""

import re
from datetime import datetime, timezone

from payment import repository

CARD_NUMBER_RE = re.compile(r"^\d{13,19}$")
CVC_RE = re.compile(r"^\d{3,4}$")
EXPIRY_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{2})$")


def booking_to_json(row: dict) -> dict:
    return {
        **row,
        "start_time": row["start_time"].astimezone(timezone.utc).isoformat(),
        "end_time":   row["end_time"].astimezone(timezone.utc).isoformat(),
        "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
    }


def payment_to_json(row: dict) -> dict:
    return {
        **row,
        "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
    }


def list_payments(db, booking_id):
    """Every payment attempt for a booking, oldest first.
    Returns (payload, status) - {"payments": [...]}, or an {"error": ...}."""
    if repository.get_booking(db, booking_id) is None:
        return {"error": "booking not found"}, 404
    rows = repository.get_payments_for_booking(db, booking_id)
    return {"payments": [payment_to_json(row) for row in rows]}, 200


def passes_luhn(card_number: str) -> bool:
    """Luhn checksum: from the right, double every second digit (subtracting 9
    if that gives more than 9); the digit sum must be divisible by 10."""
    total = 0
    for position, char in enumerate(reversed(card_number)):
        digit = int(char)
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_card(card_number, expiry, cvc) -> str | None:
    """Returns an error message, or None if the (mocked) card looks valid -
    right shape, passes the Luhn checksum and not expired. Still no network
    check: it says nothing about whether the card really exists."""
    if not isinstance(card_number, str) or not CARD_NUMBER_RE.match(card_number):
        return "card_number must be 13-19 digits"
    if not passes_luhn(card_number):
        return "card_number is not a valid card number"
    if not isinstance(cvc, str) or not CVC_RE.match(cvc):
        return "cvc must be 3 or 4 digits"
    if not isinstance(expiry, str):
        return "expiry must be in MM/YY format"
    match = EXPIRY_RE.match(expiry)
    if match is None:
        return "expiry must be in MM/YY format"
    month, year = int(match.group(1)), 2000 + int(match.group(2))
    now = datetime.now(timezone.utc)
    if (year, month) < (now.year, now.month):
        return "card has expired"
    return None


def pay_booking(db, booking_id, body):
    """Pay a booking from the JSON body of POST /bookings/<id>/pay.
    Returns (payload, status)."""
    if not isinstance(body, dict):
        body = {}
    return mark_booking_paid(
        db,
        booking_id,
        body.get("card_number"),
        body.get("expiry"),
        body.get("cvc"),
        force_failure=body.get("force_failure") is True,
    )


def mark_booking_paid(db, booking_id, card_number, expiry, cvc, force_failure=False):
    """Mocked payment: no provider, so it succeeds unless force_failure
    is set or the card doesn't look valid (see validate_card). Paying an
    already-paid booking is a no-op rather than an error, so a retried
    request can't break the flow or charge twice - and doesn't need a
    card either. Only the card's last 4 digits are ever stored.
    Returns (payload, status) - the booking, or an {"error": ...}."""
    row = repository.get_booking(db, booking_id)
    if row is None:
        return {"error": "booking not found"}, 404

    if row["paid"]:
        return booking_to_json(row), 200

    card_error = validate_card(card_number, expiry, cvc)
    if card_error:
        return {"error": card_error}, 400

    if force_failure:
        record_payment(db, row, "failed", card_number[-4:], reason="payment failed")
        return {"error": "payment failed"}, 402

    row = repository.mark_paid(db, booking_id, card_number[-4:])
    record_payment(db, row, "success", card_number[-4:])
    return booking_to_json(row), 200


def record_payment(db, booking, status, card_last4, reason=None):
    """Store a payment attempt in the payments table. A free booking (amount
    0) has no money to record - the table only accepts amounts above 0."""
    if not booking["amount_cents"]:
        return
    repository.insert_payment(
        db,
        booking["id"],
        booking["amount_cents"],
        status,
        reason=reason,
        card_last4=card_last4,
    )
