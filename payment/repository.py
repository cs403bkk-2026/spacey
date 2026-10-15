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


def insert_refund(
    db,
    booking_id,
    amount_cents,
    currency="USD",
    reason="cancellation",
    card_last4=None,
):
    """Record a refund for a booking in the payments table."""
    return insert_payment(
        db,
        booking_id=booking_id,
        amount_cents=amount_cents,
        status="refunded",
        currency=currency,
        reason=reason,
        card_last4=card_last4,
    )

