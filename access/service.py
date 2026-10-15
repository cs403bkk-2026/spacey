
import secrets

from flask import current_app as app

from access import client, functions
from shared.logger import logger


def issue_access_code(booking_id, booking=None):
    """Shared by the JSON API and the Unlock button.
    The caller (Purchase) has already checked the booking exists and is paid;
    Access never reads bookings: the hub passes the booking (for its times).
    Returns (payload, status): {booking_id, access_code}, 200.

    With ACCESS_URL set, the code comes from spacey-access (get-or-create, so
    every unlock of a booking gives the same code); otherwise from spacey's
    own access table, as on main. A failing service raises AccessUnavailable,
    which the hub answers with 503."""
    if client.enabled():
        return _issue_via_service(booking_id, booking)
    # One code per booking: the first unlock stores one, every later unlock
    # gets that same code back. ON CONFLICT ... DO UPDATE (rather than DO
    # NOTHING) so the existing row is still returned.
    with app.db.cursor() as cur:
        cur.execute(
            "INSERT INTO access (booking_id, access_code) VALUES (%s, %s) "
            "ON CONFLICT (booking_id) DO UPDATE "
            "SET access_code = access.access_code "
            "RETURNING access_code",
            (booking_id, secrets.token_hex(4)),  # mocked lock integration
        )
        access_code = cur.fetchone()["access_code"]

    return {"booking_id": booking_id, "access_code": access_code}, 200


def _issue_via_service(booking_id, booking):
    if booking is None:  # the hub always passes it; without times there is no expiry
        raise client.AccessUnavailable(f"unlock {booking_id}: no booking facts passed")
    payload, status = functions.create_access(booking_id, booking["start_time"], booking["end_time"])
    if status not in (200, 201):  # 400: the hub sent times the service refused
        raise client.AccessUnavailable(f"POST /bookings/{booking_id}/access: {status}")
    # The frozen contract (openapi.yaml): exactly these two fields, always 200.
    return {"booking_id": booking_id, "access_code": payload["access_code"]}, 200


def revoke_on_cancel(booking_id):
    """After Purchase has cancelled a booking, its code must stop working.

    Never changes the cancel answer: the booking is already cancelled. With
    ACCESS_URL unset there is nothing to do (spacey's own access row went with
    the booking, ON DELETE CASCADE). With it set, spacey-access revokes it:
      200 revoked · 404 never unlocked · 409 already used or expired (final),
    all fine. If the service is down the miss is logged; the data copy's
    "no booking -> revoked" rule (spacey-access scripts/migrate_from_spacey.py)
    repairs it later. Never logs a code."""
    if not client.enabled():
        return
    try:
        _, status = functions.revoke_access(booking_id)
    except client.AccessUnavailable as error:
        logger.warning("access revoke_on_cancel booking_id=%s outcome=unavailable (%s)", booking_id, error)
        return
    outcome = {200: "revoked", 404: "no_access", 409: "final_state"}.get(status, str(status))
    logger.info("access revoke_on_cancel booking_id=%s outcome=%s", booking_id, outcome)
