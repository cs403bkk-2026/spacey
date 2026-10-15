"""Served by spacey-purchase; this module calls it through `purchase/client.py`."""

from datetime import timezone

from psycopg import Error as DatabaseError

from shared.logger import logger
from payment.services import authorize_card
from payment.services import refund_payment
from purchase import client, mirror


def booking_to_json(row: dict) -> dict:
    """A booking row ready for jsonify: its times as UTC ISO 8601 strings."""
    return {
        **row,
        "start_time": row["start_time"].astimezone(timezone.utc).isoformat(),
        "end_time": row["end_time"].astimezone(timezone.utc).isoformat(),
        "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
    }


def create_booking(cur, space_id, member, start_time, end_time, party_size, user_id):
    """Book a space for a member; user_id is the logged-in account or None.
    member is the name as sent: trimmed, "guest" if missing or blank.
    Returns (payload, status) - the raw booking row, or an {"error": ...}."""
    # cur is unused; the signature stays the same as spacey-purchase's.
    payload, status = client.create_booking(
        space_id, member, start_time, end_time, party_size, user_id)
    if status == 201:
        mirror.booking(payload)
    return payload, status


def list_bookings(cur) -> list:
    return client.list_bookings()


def list_space_bookings(cur, space_id) -> list:
    return client.list_space_bookings(space_id)


def list_user_bookings(cur, user_id) -> list:
    """Bookings made while logged in as user_id; guest bookings never match."""
    return client.list_user_bookings(user_id)


def get_booking(cur, booking_id) -> dict | None:
    return client.get_booking(booking_id)


def check_payable(cur, booking_id):
    """May Payment collect, and how much? Collect only when status is
    "pending"; "completed" means already paid.
    Returns ({"id", "amount_cents", "status"}, 200) or ({"error": ...}, 404)."""
    return client.check_payable(booking_id)


def check_unlockable(cur, booking_id) -> tuple[dict, int] | None:
    """Purchase's check before Access issues a code: the booking must exist
    and be paid. Returns (payload, status) to answer with, or None if fine."""
    return client.check_unlockable(booking_id)


def check_cancellable(cur, booking_id) -> tuple[dict, int] | None:
    """SP-R09: a booking may be cancelled only before its start, by the
    database clock. Returns (payload, status) to answer with, or None if fine."""
    return client.check_cancellable(booking_id)


def mark_paid(cur, booking_id, card_last4) -> dict | None:
    """Flip the booking to paid, keeping only the card's last 4 digits.
    Returns the updated row."""
    row = client.mark_paid(booking_id, card_last4)
    if row is not None:
        mirror.booking(row)
    return row


def mark_booking_paid(cur, booking_id, card_number, expiry, cvc, force_failure=False):
    """Pay for a booking. Payment decides whether the card is accepted
    (payment.services.authorize_card); this owns the booking's paid state.
    Paying an already-paid booking is a no-op rather than an error, so a
    retried request can't break the flow or charge twice - and doesn't need
    a card either. Only the card's last 4 digits are ever stored.
    Returns (payload, status) - the raw booking row, or an {"error": ...}."""
    if client.pays():  # PUR-027: the service charges through Payments
        payload, status = client.mark_booking_paid(
            booking_id, card_number, expiry, cvc, force_failure)
        if status == 200:
            mirror.booking(payload)  # PUR-023's mirror
        return payload, status
    logger.debug("payment booking_id=%s outcome=started", booking_id)
    try:
        row = get_booking(cur, booking_id)
        if row is None:
            logger.warning("payment booking_id=%s outcome=not_found", booking_id)
            return {"error": "booking not found"}, 404

        if row["paid"]:
            logger.info("payment booking_id=%s outcome=already_paid", booking_id)
            return row, 200

        # ADR 0003: Purchase checks the hold before the card is charged.
        # Only the service has the 15-minute hold, so the check runs only when
        # the service answers. Otherwise /pay behaves exactly as before.
        use_service = client.enabled()
        if use_service:
            facts, status = check_payable(cur, booking_id)
            if status != 200:  # 409: the hold has expired; 404: cancelled since
                outcome = "hold_expired" if status == 409 else "not_found"
                logger.warning("payment booking_id=%s outcome=%s", booking_id, outcome)
                return facts, status

        rejected = authorize_card(card_number, expiry, cvc, force_failure)
        if rejected:
            outcome = "invalid_card" if rejected[1] == 400 else "failed"
            logger.warning("payment booking_id=%s outcome=%s", booking_id, outcome)
            return rejected

        booking = row  # mark_paid replaces row; the refund needs the amount
        row = mark_paid(cur, booking_id, card_number[-4:])
        if row is None and use_service:  # the service refused the late payment
            logger.warning("payment booking_id=%s outcome=refused", booking_id)
            if booking["amount_cents"] > 0:  # as on cancel: a refund of 0 fails
                refund_payment(
                    cur.connection,
                    booking_id=booking_id,
                    amount_cents=booking["amount_cents"],
                    card_last4=card_number[-4:],
                    reason="hold_expired",
                )
            return check_payable(cur, booking_id)  # 409 (or 404), never a 500
        logger.info("payment booking_id=%s outcome=succeeded", booking_id)
        return row, 200
    except DatabaseError:
        # Database diagnostics may include SQL parameters; never log the exception.
        logger.error("payment booking_id=%s outcome=database_error", booking_id)
        return {"error": "payment unavailable"}, 500


def cancel_booking(cur, booking_id) -> dict | None:
    """Delete a booking (its access code goes with it); None if not found."""
    row = client.cancel_booking(booking_id)
    if row is not None:
        mirror.cancel(booking_id)
    return row
