import re
from datetime import datetime, timezone

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


def member_key(name: str) -> str:
    return name.strip().lower()


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


def pay_booking(app, booking_id, body):
    """Pay a booking from the JSON body of POST /bookings/<id>/pay.
    Returns (payload, status)."""
    if not isinstance(body, dict):
        body = {}
    return mark_booking_paid(
        app,
        booking_id,
        body.get("card_number"),
        body.get("expiry"),
        body.get("cvc"),
        force_failure=body.get("force_failure") is True,
    )


def mark_booking_paid(app, booking_id, card_number, expiry, cvc, force_failure=False):
    """Mocked payment: no provider, so it succeeds unless force_failure
    is set or the card doesn't look valid (see validate_card). Paying an
    already-paid booking is a no-op rather than an error, so a retried
    request can't break the flow or charge twice - and doesn't need a
    card either. Only the card's last 4 digits are ever stored.
    Returns (payload, status) - the booking, or an {"error": ...}."""
    with app.db.cursor() as cur:
        cur.execute(
            "SELECT id, space_id, member, paid, start_time, end_time, "
            "amount_cents, user_id, card_last4, created_at "
            "FROM bookings WHERE id = %s",
            (booking_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"error": "booking not found"}, 404

        if row["paid"]:
            return booking_to_json(row), 200

        card_error = validate_card(card_number, expiry, cvc)
        if card_error:
            return {"error": card_error}, 400

        if force_failure:
            return {"error": "payment failed"}, 402

        cur.execute(
            "UPDATE bookings SET paid = TRUE, card_last4 = %s WHERE id = %s "
            "RETURNING id, space_id, member, paid, start_time, end_time, "
            "amount_cents, user_id, card_last4, created_at",
            (card_number[-4:], booking_id),
        )
        row = cur.fetchone()

    return booking_to_json(row), 200
