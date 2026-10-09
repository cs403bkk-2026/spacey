"""HTTP routes for payments. Parses the request, calls services.py, and
shapes the response - no business rules or SQL here."""

from flask import Blueprint, current_app, jsonify

from payment import services

payment_bp = Blueprint("payment", __name__)


@payment_bp.get("/bookings/<int:booking_id>/payments")
def list_payments(booking_id):
    payload, status = services.list_payments(current_app.db, booking_id)
    return jsonify(payload), status
