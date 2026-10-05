"""Purchase owns expiry of unpaid booking holds."""


def expire_unpaid_bookings(cur):
    """Release unpaid holds 15 minutes after creation, like cancellation.

    ponytail: expired bookings are deleted, matching cancellation; retain
    historical rows when Purchase introduces a booking status model.
    """
    cur.execute(
        "DELETE FROM bookings WHERE NOT paid "
        "AND created_at <= statement_timestamp() - INTERVAL '15 minutes'"
    )
