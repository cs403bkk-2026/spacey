"""HTTP routes for paying a booking. Parses the request, calls purchase.booking
(which asks payment.services whether the card is accepted), and shapes the
response - no business rules or SQL here."""

from flask import Blueprint, current_app, request

import purchase.booking
from payment import responses

booking_bp = Blueprint("booking", __name__)


@booking_bp.post("/bookings/<int:booking_id>/pay")
def pay_booking(booking_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    with current_app.db.cursor() as cur:
        payload, status = purchase.booking.mark_booking_paid(
            cur,
            booking_id,
            body.get("card_number"),
            body.get("expiry"),
            body.get("cvc"),
            force_failure=body.get("force_failure") is True,
        )
    if status == 200:
        payload = purchase.booking.booking_to_json(payload)
    return responses.json_response(payload, status, request.path)
