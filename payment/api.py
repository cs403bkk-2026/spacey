"""HTTP routes for payments. Parses the request, calls services.py, and
shapes the response - no business rules or SQL here."""

from flask import Blueprint, current_app, jsonify, redirect, request, url_for

from payment import services

payment_bp = Blueprint("payment", __name__)


@payment_bp.post("/bookings/<int:booking_id>/pay")
def pay_booking(booking_id):
    payload, status = services.pay_booking(
        current_app.db, booking_id, request.get_json(silent=True) or {}
    )
    return jsonify(payload), status


@payment_bp.get("/bookings/<int:booking_id>/payments")
def list_payments(booking_id):
    payload, status = services.list_payments(current_app.db, booking_id)
    return jsonify(payload), status


@payment_bp.post("/bookings/<int:booking_id>/confirmation/pay")
def pay_from_confirmation(booking_id):
    payload, status = services.mark_booking_paid(
        current_app.db,
        booking_id,
        request.form.get("card_number"),
        request.form.get("expiry"),
        request.form.get("cvc"),
    )
    if status >= 400:
        return redirect(
            url_for("booking_confirmation", booking_id=booking_id, error=payload["error"])
        )
    return redirect(url_for("booking_confirmation", booking_id=booking_id))
