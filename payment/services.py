"""Payment business rules: card validation and the (mocked) payment flow.
No Flask and no SQL - HTTP lives in api.py, the database in repository.py."""

import re
from datetime import datetime, timezone

from payment import repository
from payment.responses import booking_to_json, error_body

CARD_NUMBER_RE = re.compile(r"^\d{13,19}$")
CVC_RE = re.compile(r"^\d{3,4}$")
EXPIRY_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{2})$")


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


def validate_card(card_number, expiry, cvc) -> dict | None:
    """Error body, or None if the card has the right shape, passes Luhn,
    and is not expired. No network check."""
    if not isinstance(card_number, str) or not CARD_NUMBER_RE.match(card_number):
        return error_body(
            400, "card_number must be 13-19 digits",
            "invalid_card_number", "/card_number",
        )
    if not passes_luhn(card_number):
        return error_body(
            400, "card_number is not a valid card number",
            "invalid_card_number", "/card_number",
        )
    if not isinstance(cvc, str) or not CVC_RE.match(cvc):
        return error_body(400, "cvc must be 3 or 4 digits", "invalid_cvc", "/cvc")
    if not isinstance(expiry, str):
        return error_body(
            400, "expiry must be in MM/YY format", "invalid_expiry", "/expiry",
        )
    match = EXPIRY_RE.match(expiry)
    if match is None:
        return error_body(
            400, "expiry must be in MM/YY format", "invalid_expiry", "/expiry",
        )
    month, year = int(match.group(1)), 2000 + int(match.group(2))
    now = datetime.now(timezone.utc)
    if (year, month) < (now.year, now.month):
        return error_body(400, "card has expired", "card_expired", "/expiry")
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
    Returns (payload, status): the booking, or an error body."""
    row = repository.get_booking(db, booking_id)
    if row is None:
        return error_body(404, "booking not found", "booking_not_found"), 404

    if row["paid"]:
        return booking_to_json(row), 200

    card_error = validate_card(card_number, expiry, cvc)
    if card_error:
        return card_error, 400

    if force_failure:
        return error_body(402, "payment failed", "payment_failed"), 402

    row = repository.mark_paid(db, booking_id, card_number[-4:])
    return booking_to_json(row), 200
