import re
from datetime import datetime, timezone

CARD_NUMBER_RE = re.compile(r"^\d{13,19}$")
CVC_RE = re.compile(r"^\d{3,4}$")
EXPIRY_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{2})$")


def member_key(name: str) -> str:
    return name.strip().lower()


def validate_card(card_number, expiry, cvc) -> str | None:
    """Returns an error message, or None if the (mocked) card looks valid -
    right shape and not expired, not a real Luhn/network check."""
    if not isinstance(card_number, str) or not CARD_NUMBER_RE.match(card_number):
        return "card_number must be 13-19 digits"
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


def mark_booking_paid(app, booking_id, card_number, expiry, cvc, force_failure=False):
    """Mocked payment: no provider, so it succeeds unless force_failure
    is set or the card doesn't look valid (see validate_card). Paying an
    already-paid booking is a no-op rather than an error, so a retried
    request can't break the flow or charge twice - and doesn't need a
    card either. Only the card's last 4 digits are ever stored.
    Returns (payload, status) - the booking, or an {"error": ...}."""
    with app.db.cursor() as cur:
        cur.execute(
            "SELECT id, member, paid, amount_cents, card_last4 "
            "FROM bookings WHERE id = %s",
            (booking_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"error": "booking not found"}, 404

        if row["paid"]:
            return row, 200

        card_error = validate_card(card_number, expiry, cvc)
        if card_error:
            return {"error": card_error}, 400

        if force_failure:
            return {"error": "payment failed"}, 402

        cur.execute(
            "UPDATE bookings SET paid = TRUE, card_last4 = %s WHERE id = %s "
            "RETURNING id, member, paid, amount_cents, card_last4",
            (card_number[-4:], booking_id),
        )
        row = cur.fetchone()

    return row, 200
