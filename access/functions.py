"""The 6 access functions the hub calls. Each is one call to spacey-access
(access/client.py) and returns (payload, status) exactly as the service
answered, for every answer its contract allows. Anything else raises
AccessUnavailable, which the hub answers with 503.

Access never reads Purchase's data: the hub passes the booking's facts in.
"""

from datetime import datetime

from access import client


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def create_access(booking_id, start_time, end_time):
    """Get-or-create: 201 the first time, 200 with the same record after."""
    return client.call("POST", f"/bookings/{booking_id}/access",
                       {"start_time": _iso(start_time), "end_time": _iso(end_time)},
                       expect=(200, 201, 400))


def read_access(booking_id):
    return client.call("GET", f"/bookings/{booking_id}/access", expect=(200, 404))


def revoke_access(booking_id):
    return client.call("POST", f"/bookings/{booking_id}/access/revoke", expect=(200, 404, 409))


def check_in(booking_id, access_code):
    return client.call("POST", f"/bookings/{booking_id}/check-in", {"access_code": access_code},
                       expect=(200, 400, 403, 404, 409))


def check_out(booking_id):
    return client.call("POST", f"/bookings/{booking_id}/check-out", expect=(200, 404, 409))


def expire_access(booking_id):
    return client.call("POST", f"/bookings/{booking_id}/access/expire", expect=(200, 404, 409))
