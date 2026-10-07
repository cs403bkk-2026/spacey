"""HTTP routes for payments. Parses the request, calls services.py, and
shapes the response - no business rules or SQL here."""
from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, request, url_for

from payment import services
from payment.models.card import Card

payment_bp = Blueprint("payment", __name__)


@payment_bp.post("/bookings/<int:booking_id>/pay")
def pay_booking(booking_id):
    body: dict[str, Any] = request.get_json(silent=True) or {}
    if (card := Card.from_body(body)) is None:
        return dict(error="Couldn't extract card info"), 400

    payload, status = services.mark_booking_paid(
        current_app.db,
        booking_id,
        card,
        force_failure=body.get("force_failure", False)
    )
    return jsonify(payload), status


@payment_bp.post("/bookings/<int:booking_id>/confirmation/pay")
def pay_from_confirmation(booking_id):
    if (card := Card.from_body(request.form)) is None:
        return redirect(url_for(
            "booking_confirmation",
            booking_id=booking_id,
            error="Could not extract card"
        ))

    payload, status = services.mark_booking_paid(
        current_app.db,
        booking_id,
        card,
        force_failure=request.form.get("force_failure", False)
    )
    if status >= 400:
        return redirect(url_for(
            "booking_confirmation",
            booking_id=booking_id,
            error=payload["error"]
        ))

    return redirect(url_for(
        "booking_confirmation",
        booking_id=booking_id
    ))
