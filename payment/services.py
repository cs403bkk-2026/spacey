"""Payment business rules: card validation, the (mocked) provider, and the
functions Purchase calls - collect, payment_status and refund_payment.
No Flask, no SQL and no bookings - the database lives in repository.py, and
purchase.booking owns a booking's paid state."""

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


class ProviderUnavailable(Exception):
    """The provider gave no answer, so the charge may or may not have gone
    through. The mock never raises it; tests do, to stand in for a timeout."""


def charge_card(amount_cents, card_number, expiry, cvc, force_failure=False):
    """The mocked provider: no network and no real money. Returns None if
    the charge went through, or the reason it was declined."""
    if force_failure:
        return "payment failed"
    return None


# Stored status -> the status collect and payment_status report (ADR 0004).
REPORTED_STATUS = {"success": "paid", "failed": "failed", "unknown": "unknown"}


def outcome(status, payment_id=None, error=None):
    return {"status": status, "payment_id": payment_id, "error": error}


def collect(db, booking_id, amount_cents, card_number, expiry, cvc, force_failure=False):
    """ADR 0004's collect: charge a booking's amount at most once. Purchase
    gives the booking's id and stored price; nothing here reads or updates
    bookings. Returns {"status", "payment_id", "error"} with status:
    - "paid": charged, now or by an earlier call (then the same payment_id).
    - "failed": declined, stored as a failed attempt; another try is allowed.
      Invalid card details also fail, with payment_id None: nothing was tried.
    - "unknown": an attempt is still in progress or its answer was lost.
      Nothing is charged again until that attempt is settled.
    A free booking (amount 0) has nothing to collect: "paid", nothing stored."""
    card_error = validate_card(card_number, expiry, cvc)
    if card_error:
        return outcome("failed", error=card_error)
    if amount_cents == 0:
        return outcome("paid")

    while (attempt := repository.start_attempt(
            db, booking_id, amount_cents, card_number[-4:])) is None:
        existing = repository.get_open_or_paid_attempt(db, booking_id)
        if existing is not None:  # another call got there first
            return outcome(REPORTED_STATUS[existing["status"]], existing["id"])
        # That attempt failed in the meantime, so this one may start.

    try:
        declined = charge_card(amount_cents, card_number, expiry, cvc, force_failure)
    except ProviderUnavailable:
        # Not a failure: the card may have been charged. The row stays
        # "unknown", which also blocks a second charge.
        return outcome("unknown", attempt["id"])
    if declined:
        repository.finish_attempt(db, attempt["id"], "failed", reason=declined)
        return outcome("failed", attempt["id"], declined)
    repository.finish_attempt(db, attempt["id"], "success")
    return outcome("paid", attempt["id"])


def payment_status(db, booking_id):
    """ADR 0004's status lookup: {"status", "payment_id"} with status "paid",
    "unknown" (in progress or answer lost - never proof that nothing was
    charged), "failed" (the latest attempt was declined) or "none"."""
    attempt = repository.get_open_or_paid_attempt(db, booking_id)
    if attempt is None:
        failed = [p for p in repository.get_payments_for_booking(db, booking_id)
                  if p["status"] == "failed"]
        attempt = failed[-1] if failed else None
    if attempt is None:
        return {"status": "none", "payment_id": None}
    return {"status": REPORTED_STATUS[attempt["status"]], "payment_id": attempt["id"]}


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

