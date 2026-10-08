
import secrets

from flask import current_app as app


def issue_access_code(booking_id):
    """Shared by the JSON API and the Unlock button.
    Returns (payload, status)."""
    with app.db.cursor() as cur:
        cur.execute(
            "SELECT id, paid FROM bookings WHERE id = %s", (booking_id,)
        )
        booking = cur.fetchone()

    if booking is None:
        return {"error": "booking not found"}, 404
    if not booking["paid"]:
        return {"error": "booking is not paid"}, 402

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

# --- Access state functions (spacey-access#1) ---
# Only the access table is used; time comes from the caller (now);
# each state change is one UPDATE that re-checks the status.

ACCEPTED = "accepted"
UNKNOWN_CODE = "unknown_code"
REMOVED = "removed"
EXPIRED = "expired"
NOT_YET = "not_yet"
ALREADY_IN = "already_in"
NOT_CHECKED_IN = "not_checked_in"
NO_INTERVAL = "no_interval"

ACCESS_COLUMNS = (
    "booking_id, access_code, access_status, created_at, booked_start_time, "
    "booked_end_time, expires_at, checked_in_at, checked_out_at, removed_at, "
    "space_id"
)


def _expire_code_if_overdue(cur, access_code, now):
    cur.execute(
        "UPDATE access SET access_status = 'expired' "
        "WHERE access_code = %s AND access_status IN ('available', 'used') "
        "AND expires_at <= %s",
        (access_code, now),
    )


def _find_by_code(cur, access_code):
    cur.execute(
        f"SELECT {ACCESS_COLUMNS} FROM access WHERE access_code = %s",
        (access_code,),
    )
    return cur.fetchone()


def get_access(cur, booking_id, now):
    """Read one access record (None if none); applies lazy expiry first."""
    cur.execute(
        "UPDATE access SET access_status = 'expired' "
        "WHERE booking_id = %s AND access_status IN ('available', 'used') "
        "AND expires_at <= %s",
        (booking_id, now),
    )
    cur.execute(
        f"SELECT {ACCESS_COLUMNS} FROM access WHERE booking_id = %s",
        (booking_id,),
    )
    return cur.fetchone()


def check_in(cur, access_code, now):
    """available + booked_start_time <= now < expires_at -> used."""
    _expire_code_if_overdue(cur, access_code, now)
    cur.execute(
        "UPDATE access SET access_status = 'used', checked_in_at = %s "
        "WHERE access_code = %s AND access_status = 'available' "
        "AND booked_start_time <= %s AND %s < expires_at "
        "RETURNING booking_id",
        (now, access_code, now, now),
    )
    if cur.fetchone() is not None:
        return ACCEPTED

    row = _find_by_code(cur, access_code)
    if row is None:
        return UNKNOWN_CODE
    if row["access_status"] == "removed":
        return REMOVED
    if row["access_status"] == "expired":
        return EXPIRED
    if row["access_status"] == "used":
        return ALREADY_IN
    if row["booked_start_time"] is None or row["expires_at"] is None:
        return NO_INTERVAL
    return NOT_YET


def check_out(cur, access_code, now):
    """used -> available (re-entry allowed until expiry)."""
    _expire_code_if_overdue(cur, access_code, now)
    cur.execute(
        "UPDATE access SET access_status = 'available', checked_out_at = %s "
        "WHERE access_code = %s AND access_status = 'used' "
        "RETURNING booking_id",
        (now, access_code),
    )
    if cur.fetchone() is not None:
        return ACCEPTED

    row = _find_by_code(cur, access_code)
    if row is None:
        return UNKNOWN_CODE
    if row["access_status"] == "removed":
        return REMOVED
    if row["access_status"] == "expired":
        return EXPIRED
    return NOT_CHECKED_IN


def remove_access(cur, booking_id, now):
    """Purchase cancelled: available/used -> removed. Never deletes the row."""
    cur.execute(
        "UPDATE access SET access_status = 'removed', removed_at = %s "
        "WHERE booking_id = %s AND access_status IN ('available', 'used') "
        "RETURNING booking_id",
        (now, booking_id),
    )
    return cur.fetchone() is not None


def expire_overdue(cur, now):
    """Sweep: every overdue available/used record -> expired. Returns count."""
    cur.execute(
        "UPDATE access SET access_status = 'expired' "
        "WHERE access_status IN ('available', 'used') AND expires_at <= %s",
        (now,),
    )
    return cur.rowcount


def change_interval(cur, booking_id, start_time, end_time, expires_at=None):
    """Purchase moved the booking. Refused for removed. Expired stays expired."""
    cur.execute(
        "UPDATE access SET booked_start_time = %s, booked_end_time = %s, "
        "expires_at = %s "
        "WHERE booking_id = %s AND access_status <> 'removed' "
        "RETURNING booking_id",
        (start_time, end_time, expires_at or end_time, booking_id),
    )
    return cur.fetchone() is not None