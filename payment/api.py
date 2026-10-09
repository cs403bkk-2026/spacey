"""HTTP routes for payments. Parses the request, calls services.py, and
shapes the response - no business rules or SQL here."""

from flask import Blueprint, jsonify, request

from payment import services

payment_bp = Blueprint("payment", __name__)


@payment_bp.post("/payment/bookings/<int:booking_id>/pay")
def pay_booking(booking_id):
    payload, status = services.pay_booking(
        booking_id, request.get_json(silent=True)
    )
    return jsonify(payload), status
