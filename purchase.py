"""Purchase owns expiry of unpaid booking holds."""

from datetime import timedelta

UNPAID_HOLD_DURATION = timedelta(minutes=15)


def expire_unpaid_bookings(cur):
    """Release unpaid holds 15 minutes after creation, like cancellation.

    ponytail: expired bookings are deleted, matching cancellation; retain
    historical rows when Purchase introduces a booking status model.
    """
    cur.execute(
        "DELETE FROM bookings WHERE NOT paid "
        "AND created_at <= statement_timestamp() - %s",
        (UNPAID_HOLD_DURATION,),
    )
