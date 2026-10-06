"""The access table change in get_connection() (docs/access-table.md).

Schema only: the access functions are unchanged, so these tests reach them
through the existing routes and read the table directly.
"""
from datetime import datetime, timedelta, timezone

from app import create_app

NOW = datetime.now(timezone.utc)
CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}
NEW_COLUMNS = {
    "access_status", "booked_start_time", "booked_end_time", "expires_at",
    "checked_in_at", "checked_out_at", "removed_at", "space_id",
}


def slot(start_hours, end_hours):
    return {
        "start_time": (NOW + timedelta(hours=start_hours)).isoformat(),
        "end_time": (NOW + timedelta(hours=end_hours)).isoformat(),
    }


def unlocked_booking(client, start_hours=24, end_hours=25):
    """Book, pay and unlock through the API: the current way a row appears."""
    booking = client.post(
        "/spaces/1/bookings", json={"member": "member a", **slot(start_hours, end_hours)}
    ).get_json()
    client.post(f"/bookings/{booking['id']}/pay", json=CARD)
    client.post(f"/bookings/{booking['id']}/unlock")
    return booking


def access_row(app, booking_id):
    with app.db.cursor() as cur:
        cur.execute("SELECT * FROM access WHERE booking_id = %s", (booking_id,))
        return cur.fetchone()


def restart():
    """A second app on the same database, as after a redeploy."""
    return create_app(reset_on_start=False)


def test_the_access_table_has_the_new_columns():
    app = create_app(reset_on_start=True)
    with app.db.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'access'"
        )
        columns = {row["column_name"] for row in cur.fetchall()}

    assert NEW_COLUMNS <= columns
    assert {"booking_id", "access_code", "created_at"} <= columns


def test_a_new_access_row_is_available():
    app = create_app(reset_on_start=True)
    booking = unlocked_booking(app.test_client())

    row = access_row(app, booking["id"])

    assert row["access_status"] == "available"
    assert row["checked_in_at"] is None
    assert row["checked_out_at"] is None
    assert row["removed_at"] is None


def test_a_restart_copies_the_booking_interval_and_sets_the_expiry():
    app = create_app(reset_on_start=True)
    booking = unlocked_booking(app.test_client())

    again = restart()
    row = access_row(again, booking["id"])

    assert row["booked_start_time"].isoformat() == booking["start_time"]
    assert row["booked_end_time"].isoformat() == booking["end_time"]
    assert row["expires_at"] == row["booked_end_time"]
    assert row["space_id"] == 1


def test_cancelling_a_booking_keeps_its_access_row():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    booking = unlocked_booking(client)

    assert client.delete(f"/bookings/{booking['id']}").status_code == 200

    assert access_row(app, booking["id"]) is not None
    # The API still behaves as before: the booking is gone.
    assert client.post(f"/bookings/{booking['id']}/unlock").status_code == 404


def test_an_overdue_access_row_becomes_expired_on_restart():
    app = create_app(reset_on_start=True)
    booking = unlocked_booking(app.test_client(), start_hours=-3, end_hours=-2)

    row = access_row(restart(), booking["id"])

    assert row["access_status"] == "expired"


def test_a_restart_does_not_rewrite_recorded_states():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    used, removed = unlocked_booking(client, 24, 25), unlocked_booking(client, 48, 49)
    with app.db.cursor() as cur:
        cur.execute(
            "UPDATE access SET access_status = 'used', checked_in_at = %s WHERE booking_id = %s",
            (NOW, used["id"]),
        )
        cur.execute(
            "UPDATE access SET access_status = 'removed', removed_at = %s WHERE booking_id = %s",
            (NOW, removed["id"]),
        )

    again = restart()

    assert access_row(again, used["id"])["access_status"] == "used"
    assert access_row(again, used["id"])["checked_in_at"] == NOW
    assert access_row(again, removed["id"])["access_status"] == "removed"


def test_an_existing_old_access_table_is_migrated():
    """The table as on main before this change: three columns and the
    ON DELETE CASCADE foreign key."""
    app = create_app(reset_on_start=True)
    booking = unlocked_booking(app.test_client())
    with app.db.cursor() as cur:
        cur.execute(
            "ALTER TABLE access DROP COLUMN access_status, DROP COLUMN booked_start_time, "
            "DROP COLUMN booked_end_time, DROP COLUMN expires_at, DROP COLUMN checked_in_at, "
            "DROP COLUMN checked_out_at, DROP COLUMN removed_at, DROP COLUMN space_id"
        )
        cur.execute(
            "ALTER TABLE access ADD CONSTRAINT access_booking_id_fkey "
            "FOREIGN KEY (booking_id) REFERENCES bookings (id) ON DELETE CASCADE"
        )

    again = restart()
    row = access_row(again, booking["id"])
    with again.db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = 'access_booking_id_fkey'"
        )
        fk_left = cur.fetchone()

    assert row["access_status"] == "available"
    assert row["access_code"]
    assert row["booked_end_time"].isoformat() == booking["end_time"]
    assert row["expires_at"] == row["booked_end_time"]
    assert fk_left is None
