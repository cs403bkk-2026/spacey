from datetime import timezone

from flask import jsonify, request

from validation import validate_card


def member_key(name: str) -> str:
    return name.strip().lower()


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


def pay_booking(booking_id):
    body = request.get_json(silent=True) or {}
    payload, status = mark_booking_paid(
        booking_id,
        body.get("card_number"),
        body.get("expiry"),
        body.get("cvc"),
        force_failure=body.get("force_failure") is True,
    )
    return jsonify(payload), status


def subscribe_member(name):
    # Mocked, like payment: no provider, always succeeds. Subscribing
    # again is a no-op, so a retried request can't break anything.
    member = member_key(name)
    if not member:
        return jsonify(error="member name must not be blank"), 400

    with app.db.cursor() as cur:
        cur.execute(
            "INSERT INTO subscriptions (member) VALUES (%s) "
            "ON CONFLICT (member) DO UPDATE SET active = TRUE "
            "RETURNING member, active, started_at",
            (member,),
        )
        row = cur.fetchone()

    return jsonify(
        member=row["member"],
        active=row["active"],
        started_at=row["started_at"].astimezone(timezone.utc).isoformat(),
    )
