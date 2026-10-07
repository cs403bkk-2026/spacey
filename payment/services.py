"""Payment business rules: card validation and the (mocked) payment flow.
No Flask and no SQL - HTTP lives in api.py, the database in repository.py."""

import logging
import os
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
logger.addHandler(handler)
logger.propagate = False

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


def pay_booking(booking_id, body):
    """Process the JSON body of POST /bookings/<id>/pay.
    Returns (payload, status)."""
    if not isinstance(body, dict):
        body = {}
    return process_payment(
        booking_id,
        body.get("card_number"),
        body.get("expiry"),
        body.get("cvc"),
        force_failure=body.get("force_failure") is True,
    )


def process_payment(booking_id, card_number, expiry, cvc, force_failure=False):
    """Return a mock outcome without reading or updating booking state.

    The booking owner handles existence checks, retries and applying success.
    Nothing is persisted; only the card's last four digits are returned.
    """
    logger.debug("payment booking_id=%s outcome=started", booking_id)
    card_error = validate_card(card_number, expiry, cvc)
    if card_error:
        logger.warning("payment booking_id=%s outcome=invalid_card", booking_id)
        return {"error": card_error}, 400

    if force_failure:
        logger.warning("payment booking_id=%s outcome=failed", booking_id)
        return {"error": "payment failed"}, 402

    logger.info("payment booking_id=%s outcome=succeeded", booking_id)
    return {
        "booking_id": booking_id,
        "status": "success",
        "card_last4": card_number[-4:],
    }, 200
