"""Payment business rules: card validation and the (mocked) payment decision.
No Flask, no SQL and no bookings - HTTP lives in api.py, the database in
repository.py, and purchase.booking owns a booking's paid state."""

import re
from datetime import datetime, timezone

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


def refund_payment(
    db=None,
    booking_id=None,
    amount_cents=None,
    card_last4=None,
    reason="cancellation",
):
    """Record a refund for a booking in the payments table.
    Delegates persistence to payment.repository.insert_refund."""
    from payment import repository

    if isinstance(db, int) and (booking_id is None or isinstance(booking_id, (int, float))):
        actual_booking_id = db
        actual_amount_cents = booking_id
        if isinstance(amount_cents, str):
            actual_reason = amount_cents
            actual_card_last4 = card_last4
        else:
            actual_reason = reason
            actual_card_last4 = card_last4
        from flask import current_app
        actual_db = current_app.db
    else:
        actual_db = db
        actual_booking_id = booking_id
        actual_amount_cents = amount_cents
        actual_card_last4 = card_last4
        actual_reason = reason

    if actual_db is None:
        from flask import current_app
        actual_db = current_app.db

    return repository.insert_refund(
        actual_db,
        booking_id=actual_booking_id,
        amount_cents=actual_amount_cents,
        reason=actual_reason,
        card_last4=actual_card_last4,
    )


refund_booking = refund_payment

