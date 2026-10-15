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


def start_attempt(db, booking_id, amount_cents, card_last4):
    """Store a new attempt as 'unknown' (in progress) and return it, or None
    if the booking already has one in progress or succeeded - the unique
    index decides, so two concurrent calls can't both get a row."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (booking_id, amount_cents, status, card_last4) "
            "VALUES (%s, %s, 'unknown', %s) "
            "ON CONFLICT (booking_id) WHERE status IN ('success', 'unknown') "
            f"DO NOTHING RETURNING {PAYMENT_COLUMNS}",
            (booking_id, amount_cents, card_last4),
        )
        return cur.fetchone()


def finish_attempt(db, payment_id, status, reason=None):
    """Settle an in-progress attempt as 'success' or 'failed'; returns the row."""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE payments SET status = %s, reason = %s "
            "WHERE id = %s AND status = 'unknown' "
            f"RETURNING {PAYMENT_COLUMNS}",
            (status, reason, payment_id),
        )
        return cur.fetchone()


def get_open_or_paid_attempt(db, booking_id):
    """The booking's attempt that is in progress or succeeded, or None."""
    with db.cursor() as cur:
        cur.execute(
            f"SELECT {PAYMENT_COLUMNS} FROM payments "
            "WHERE booking_id = %s AND status IN ('success', 'unknown')",
            (booking_id,),
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

