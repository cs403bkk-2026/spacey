"""Payment business rules: card validation and the (mocked) payment decision.
No Flask, no SQL and no bookings - HTTP lives in api.py, the database in
repository.py, and purchase.booking owns a booking's paid state."""

import re
from datetime import datetime, timezone

from payment.responses import error_body

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


def authorize_card(card_number, expiry, cvc, force_failure=False):
    """The (mocked) payment decision for one card, knowing nothing about
    bookings. Returns None if the card is accepted, otherwise (payload,
    status): 400 if it doesn't look valid (see validate_card), 402 if
    force_failure asks this attempt to fail."""
    card_error = validate_card(card_number, expiry, cvc)
    if card_error:
        return card_error, 400
    if force_failure:
        return error_body(402, "payment failed", "payment_failed"), 402
    return None
