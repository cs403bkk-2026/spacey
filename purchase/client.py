"""The hub's only link to the Purchase service (spacey-purchase).

One function per wrapper in purchase/: same name, same arguments minus `cur`,
returning what the old SQL returns. A call that gets no answer the old SQL
could have given raises PurchaseUnavailable, which the hub answers with 503.
"""

import json
import os
from datetime import datetime
from http.client import HTTPException  # http.client's, not Werkzeug's
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import flask
from psycopg.errors import ReadOnlySqlTransaction

from shared.logger import logger

TIMEOUT_S = 1.5
USER_COLUMNS = "id, email"
TIMES = ("start_time", "end_time", "created_at")


class PurchaseUnavailable(Exception):
    """The service gave no answer the old body could have given."""


def enabled() -> bool:
    return bool(os.getenv("PURCHASE_URL"))


def call(method, path, body=None, params=None, expect=(200,)):
    url = os.environ["PURCHASE_URL"].rstrip("/") + path
    if params:
        url += "?" + urlencode(params)
    data = None if body is None else json.dumps(body).encode()
    try:  # Request() raises ValueError on a bad URL
        request = Request(url, data, method=method, headers={
            "Authorization": f"Bearer {os.getenv('PURCHASE_TOKEN', '')}",
            "Content-Type": "application/json"})
        try:
            # One try, no retry: a write whose answer was lost may have
            # committed, so a retry could book twice.
            with urlopen(request, timeout=TIMEOUT_S) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:  # 4xx/5xx carry the answer
            status, raw = error.code, error.read()
        if status not in expect:
            raise PurchaseUnavailable(f"{method} {path}: {status}")
        return (None if status == 204 else json.loads(raw)), status
    except (OSError, ValueError, HTTPException) as error:
        raise PurchaseUnavailable(f"{method} {path}: {type(error).__name__}") from None


def field(payload, key):
    """payload[key]. A JSON answer without it is a link failure too."""
    try:
        return payload[key]
    except (KeyError, TypeError):
        raise PurchaseUnavailable(f"answer without {key!r}") from None


def row(data, columns) -> dict:
    """Only the old columns (no status or available leaks), times as datetime."""
    kept = {key: field(data, key) for key in columns.split(", ")}
    for key in TIMES:
        if key in kept:
            try:
                kept[key] = datetime.fromisoformat(kept[key])
            except (TypeError, ValueError):
                raise PurchaseUnavailable(f"bad {key!r}") from None
    return kept


# Imported on use: booking.py, member.py and space.py import this module.
def booking_row(data) -> dict:
    from purchase.booking import BOOKING_COLUMNS
    return row(data, BOOKING_COLUMNS)


def space_row(data) -> dict:
    from purchase.space import SPACE_COLUMNS
    return row(data, SPACE_COLUMNS)


def shaped(payload, status, ok, shape):
    """(payload, status) as the old body returns it: the row on success."""
    return (shape(payload) if status == ok else payload), status


def row_list(payload, key, shape) -> list:
    items = field(payload, key)
    if not isinstance(items, list):
        raise PurchaseUnavailable(f"{key!r} is not a list")
    return [shape(item) for item in items]


def user_row(data) -> dict:
    return row(data, USER_COLUMNS)


def payable_row(data) -> dict:
    return {key: field(data, key) for key in ("id", "amount_cents", "status")}


def list_spaces() -> list:
    payload, _ = call("GET", "/spaces")
    return row_list(payload, "spaces", space_row)


def get_space(space_id) -> dict | None:
    payload, status = call("GET", f"/spaces/{space_id}", expect=(200, 404))
    return space_row(payload) if status == 200 else None


def booked_space_ids(window) -> set:
    """Ids of the booked spaces; window is (start, end) datetimes, or None for now."""
    params = None
    if window is not None:
        start, end = window
        params = {"start_time": start.isoformat(), "end_time": end.isoformat()}
    payload, _ = call("GET", "/spaces/booked-ids", params=params)
    try:
        return set(field(payload, "space_ids"))
    except TypeError:  # not a list, or ids that are not plain values
        raise PurchaseUnavailable("bad 'space_ids'") from None


def create_space(name, capacity, price_cents):
    body = {"name": name, "capacity": capacity, "price_cents": price_cents}
    payload, status = call("POST", "/spaces", body, expect=(201, 400))
    return shaped(payload, status, 201, space_row)


def update_space(space_id, fields):
    payload, status = call(
        "PATCH", f"/spaces/{space_id}", fields, expect=(200, 400, 404))
    return shaped(payload, status, 200, space_row)


def delete_space(space_id):
    return call("DELETE", f"/spaces/{space_id}", expect=(204, 404, 409))


def register_user(email, password):
    payload, status = call(
        "POST", "/register", {"email": email, "password": password},
        expect=(201, 400, 409))
    return shaped(payload, status, 201, user_row)


def authenticate(email, password):
    payload, status = call(
        "POST", "/users/authenticate", {"email": email, "password": password},
        expect=(200, 401))
    return shaped(payload, status, 200, user_row)


def create_booking(space_id, member, start_time, end_time, party_size, user_id):
    body = {
        "member": member, "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(), "party_size": party_size,
        "user_id": user_id}
    payload, status = call(
        "POST", f"/spaces/{space_id}/bookings", body, expect=(201, 400, 404, 409))
    return shaped(payload, status, 201, booking_row)


def list_bookings() -> list:
    payload, _ = call("GET", "/bookings")
    return row_list(payload, "bookings", booking_row)


def list_space_bookings(space_id) -> list:
    payload, _ = call("GET", f"/spaces/{space_id}/bookings")
    return row_list(payload, "bookings", booking_row)


def list_user_bookings(user_id) -> list:
    payload, _ = call("GET", f"/users/{user_id}/bookings")
    return row_list(payload, "bookings", booking_row)


def get_booking(booking_id) -> dict | None:
    payload, status = call("GET", f"/bookings/{booking_id}", expect=(200, 404))
    return booking_row(payload) if status == 200 else None


def check_payable(booking_id):
    """({id, amount_cents, status}, 200) when payable, else ({"error": ...}, status)."""
    payload, status = call(
        "GET", f"/bookings/{booking_id}/payable", expect=(200, 404, 409))
    return shaped(payload, status, 200, payable_row)


def check_unlockable(booking_id):
    """None when the booking may be unlocked, else ({"error": ...}, status)."""
    payload, status = call(
        "GET", f"/bookings/{booking_id}/unlockable", expect=(204, 402, 404))
    return None if status == 204 else (payload, status)


def check_cancellable(booking_id):
    """None when the booking may be cancelled, else ({"error": ...}, status)."""
    payload, status = call(
        "GET", f"/bookings/{booking_id}/cancellable", expect=(204, 404, 409))
    return None if status == 204 else (payload, status)


def mark_paid(booking_id, card_last4) -> dict | None:
    """The row when confirmed; None when missing, cancelled or refused."""
    payload, status = call(
        "POST", f"/bookings/{booking_id}/paid", {"card_last4": card_last4},
        expect=(200, 404, 409))
    return booking_row(payload) if status == 200 else None


def cancel_booking(booking_id) -> dict | None:
    """The row as it was before the cancel, or None. A 409 means the start
    passed after check_cancellable: nothing changed; it is a link failure."""
    payload, status = call("DELETE", f"/bookings/{booking_id}", expect=(200, 404))
    return booking_row(payload) if status == 200 else None


def compute_metrics() -> dict:
    payload, _ = call("GET", "/metrics")
    if not isinstance(payload, dict):
        raise PurchaseUnavailable("metrics is not an object")
    return payload


def reset_for_tests() -> None:
    """Empty the service whenever PURCHASE_URL is set (the switch row may be
    off): it has /test/reset only when it runs with PURCHASE_TEST_RESET=1."""
    if os.getenv("PURCHASE_URL"):
        call("POST", "/test/reset", expect=(204,))


def check_link() -> None:
    """Log whether the service answers this hub with its token, so the
    switch can be checked in the hub's log (PUR-025, gunicorn.conf.py)."""
    if not os.getenv("PURCHASE_URL"):
        return
    try:
        compute_metrics()
        logger.info("purchase service check: ok")
    except PurchaseUnavailable as error:
        logger.warning("purchase service check: failed (%s)", error)
    except Exception as error:  # a log line must never stop the hub's start
        logger.warning("purchase service check: failed (%s)", type(error).__name__)


def init_app(app) -> None:
    """A broken link, or an old table frozen read-only (SQLSTATE 25006,
    the freeze at the switch), answers 503: never a 500, a false 404 or a 401."""

    def unavailable(error):
        # Method, path and reason only: never a body, a token or SQL.
        reason = (error if isinstance(error, PurchaseUnavailable)
                  else type(error).__name__)
        logger.warning(
            "purchase unavailable: %s %s (%s)",
            flask.request.method, flask.request.path, reason)
        return flask.jsonify(error="purchase unavailable"), 503

    app.register_error_handler(PurchaseUnavailable, unavailable)
    app.register_error_handler(ReadOnlySqlTransaction, unavailable)
