"""Database access for payments. SQL only - no validation or HTTP here."""

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
