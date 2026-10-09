"""Payment business rules: card validation and the (mocked) payment decision.
No Flask, no SQL and no bookings - HTTP lives in api.py, the database in
repository.py, and purchase.booking owns a booking's paid state."""

import re
from datetime import datetime, timezone

from payment import repository

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


def authorize_card(card_number, expiry, cvc, force_failure=False):
    """The (mocked) payment decision for one card, knowing nothing about
    bookings. Returns None if the card is accepted, otherwise (payload,
    status): 400 if it doesn't look valid (see validate_card), 402 if
    force_failure asks this attempt to fail."""
    card_error = validate_card(card_number, expiry, cvc)
    if card_error:
        return {"error": card_error}, 400
    if force_failure:
        return {"error": "payment failed"}, 402
    return None


def record_payment(cur, booking_id, amount_cents, status, card_last4, reason=None):
    """Store one payment attempt in the payments table, on the caller's
    connection. The caller hands over the booking's id and amount - nothing
    here reads bookings. A free booking (amount 0) has no money to record -
    the table only accepts amounts above 0."""
    if not amount_cents:
        return
    repository.insert_payment(
        cur.connection,
        booking_id,
        amount_cents,
        status,
        reason=reason,
        card_last4=card_last4,
    )


def payment_to_json(row: dict) -> dict:
    return {
        **row,
        "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
    }


def list_payments(db, booking_id):
    """Every payment attempt for a booking, oldest first. Reads only the
    payments table - no booking lookup - so an unknown booking simply has
    no payments. Returns (payload, status) - {"payments": [...]}."""
    rows = repository.get_payments_for_booking(db, booking_id)
    return {"payments": [payment_to_json(row) for row in rows]}, 200
