"""Database access for payments. SQL only - no validation or HTTP here."""

PAYMENT_COLUMNS = (
    "id, booking_id, amount_cents, currency, status, reason, "
    "card_last4, idempotency_key, created_at"
)


def insert_payment(
    db,
    booking_id,
    amount_cents,
    status,
    currency="USD",
    reason=None,
    card_last4=None,
    idempotency_key=None,
):
    """Store one payment result and return the row (its id is the payment_id).
    Only the card's last 4 digits are accepted - never the number or CVC."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (booking_id, amount_cents, currency, status, "
            "reason, card_last4, idempotency_key) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {PAYMENT_COLUMNS}",
            (booking_id, amount_cents, currency, status, reason,
             card_last4, idempotency_key),
        )
        return cur.fetchone()


def get_payments_for_booking(db, booking_id):
    """All payments for a booking, oldest first."""
    with db.cursor() as cur:
        cur.execute(
            f"SELECT {PAYMENT_COLUMNS} FROM payments "
            "WHERE booking_id = %s ORDER BY id",
            (booking_id,),
        )
        return cur.fetchall()

BOOKING_COLUMNS = (
    "id, space_id, member, paid, start_time, end_time, "
    "amount_cents, user_id, card_last4, created_at"
)


def get_booking(db, booking_id):
    """The booking row, or None if there is no such booking."""
    with db.cursor() as cur:
        cur.execute(
            f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE id = %s", (booking_id,)
        )
        return cur.fetchone()


def mark_paid(db, booking_id, card_last4):
    """Flip the booking to paid, keeping only the card's last 4 digits.
    Returns the updated row."""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE bookings SET paid = TRUE, card_last4 = %s WHERE id = %s "
            f"RETURNING {BOOKING_COLUMNS}",
            (card_last4, booking_id),
        )
        return cur.fetchone()
