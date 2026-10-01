
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

    access_code = secrets.token_hex(4)  # mocked lock integration
    return {"booking_id": booking_id, "access_code": access_code}, 200