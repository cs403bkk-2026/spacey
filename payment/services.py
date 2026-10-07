"""Payment business rules: card validation and the (mocked) payment flow.
No Flask and no SQL - HTTP lives in api.py, the database in repository.py."""

from datetime import timezone
from typing import Any

from psycopg import Connection

from payment import repository
from payment.models.card import Card


def booking_to_json(row: dict) -> dict:
    return {
        **row,
        "start_time": row["start_time"].astimezone(timezone.utc).isoformat(),
        "end_time":   row["end_time"].astimezone(timezone.utc).isoformat(),
        "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
    }


def mark_booking_paid(conn: Connection, booking_id: int, card: Card,
                      force_failure: bool = False) -> tuple[dict[str, Any], int]:
    """Mocked payment: no provider, so it succeeds unless force_failure
        is set or the card doesn't look valid (see validate_card). Paying an
        already-paid booking is a no-op rather than an error, so a retried
        request can't break the flow or charge twice - and doesn't need a
        card either. Only the card's last 4 digits are ever stored.
        Returns (payload, status) - the booking, or an {"error": ...}."""
    if force_failure:
        return {"error": "payment failed"}, 402

    if (row := repository.get_booking(conn, booking_id)) is None:
        return {"error": "booking not found"}, 404

    if row["paid"]:
        return booking_to_json(row), 200

    if card_err := card.validate():
        return {"error": card_err}, 400

    row = repository.mark_paid(conn, booking_id, card.last4)
    return booking_to_json(row), 200
