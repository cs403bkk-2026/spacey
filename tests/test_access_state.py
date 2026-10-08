"""Access state functions (spacey-access#1): check-in, check-out,
cancellation and expiry. One test per behaviour row in the issue.

Times are pinned (START, END) instead of using the clock, and access rows are
written straight into the access table, so these tests only touch Access.
"""
from datetime import datetime, timedelta, timezone

import pytest

from access import (
    ACCEPTED, ALREADY_IN, EXPIRED, NO_INTERVAL, NOT_CHECKED_IN, NOT_YET,
    REMOVED, UNKNOWN_CODE,
    change_interval, check_in, check_out, expire_overdue, get_access,
    remove_access,
)
from app import create_app

START = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=2)
DURING = START + timedelta(minutes=30)
BEFORE = START - timedelta(minutes=1)
CODE = "abcd1234"


@pytest.fixture
def cur():
    app = create_app(reset_on_start=True)
    with app.db.cursor() as cursor:
        yield cursor


def add_access(cur, booking_id=1, code=CODE, status="available",
               start=START, end=END):
    """An access row as the grant will create it: available until END."""
    cur.execute(
        "INSERT INTO access (booking_id, access_code, access_status, "
        "booked_start_time, booked_end_time, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (booking_id, code, status, start, end, end),
    )


def row(cur, booking_id=1):
    cur.execute("SELECT * FROM access WHERE booking_id = %s", (booking_id,))
    return cur.fetchone()


# --- Check-in -------------------------------------------------------------

def test_check_in_with_an_unknown_code_is_refused(cur):
    add_access(cur)

    assert check_in(cur, "nope0000", DURING) == UNKNOWN_CODE
    assert row(cur)["access_status"] == "available"


def test_check_in_on_removed_access_is_refused(cur):
    add_access(cur, status="removed")

    assert check_in(cur, CODE, DURING) == REMOVED
    assert row(cur)["checked_in_at"] is None


def test_check_in_at_or_after_expiry_is_refused_and_marks_expired(cur):
    add_access(cur)

    # exactly at expires_at counts as expired: the window is [start, expires_at)
    assert check_in(cur, CODE, END) == EXPIRED
    assert row(cur)["access_status"] == "expired"
    assert row(cur)["checked_in_at"] is None


def test_check_in_before_the_booking_starts_is_refused(cur):
    add_access(cur)

    assert check_in(cur, CODE, BEFORE) == NOT_YET
    assert row(cur)["access_status"] == "available"


def test_check_in_twice_is_refused_the_second_time(cur):
    add_access(cur)
    check_in(cur, CODE, DURING)

    assert check_in(cur, CODE, DURING + timedelta(minutes=1)) == ALREADY_IN
    assert row(cur)["checked_in_at"] == DURING


def test_check_in_inside_the_window_is_accepted(cur):
    add_access(cur)

    # exactly at the start counts as inside
    assert check_in(cur, CODE, START) == ACCEPTED
    assert row(cur)["access_status"] == "used"
    assert row(cur)["checked_in_at"] == START


def test_check_in_without_copied_times_is_refused(cur):
    # a row made by the current unlock before its times were copied in
    cur.execute(
        "INSERT INTO access (booking_id, access_code) VALUES (1, %s)", (CODE,)
    )

    assert check_in(cur, CODE, DURING) == NO_INTERVAL
    assert row(cur)["access_status"] == "available"


# --- Check-out ------------------------------------------------------------

def test_check_out_with_an_unknown_code_is_refused(cur):
    add_access(cur, status="used")

    assert check_out(cur, "nope0000", DURING) == UNKNOWN_CODE
    assert row(cur)["access_status"] == "used"


def test_check_out_on_removed_access_is_refused(cur):
    add_access(cur, status="removed")

    assert check_out(cur, CODE, DURING) == REMOVED
    assert row(cur)["checked_out_at"] is None


def test_check_out_when_checked_in_is_accepted(cur):
    add_access(cur)
    check_in(cur, CODE, DURING)
    later = DURING + timedelta(minutes=20)

    assert check_out(cur, CODE, later) == ACCEPTED
    assert row(cur)["access_status"] == "available"
    assert row(cur)["checked_out_at"] == later
    assert row(cur)["checked_in_at"] == DURING  # earlier time kept


def test_check_out_when_not_checked_in_is_refused(cur):
    add_access(cur)

    assert check_out(cur, CODE, DURING) == NOT_CHECKED_IN
    assert row(cur)["access_status"] == "available"


def test_check_out_after_expiry_is_refused_and_marks_expired(cur):
    add_access(cur)
    check_in(cur, CODE, DURING)

    assert check_out(cur, CODE, END + timedelta(minutes=5)) == EXPIRED
    assert row(cur)["access_status"] == "expired"


def test_after_check_out_the_member_can_check_in_again(cur):
    add_access(cur)
    check_in(cur, CODE, DURING)
    check_out(cur, CODE, DURING + timedelta(minutes=10))

    again = DURING + timedelta(minutes=40)
    assert check_in(cur, CODE, again) == ACCEPTED
    assert row(cur)["checked_in_at"] == again


# --- Cancellation ---------------------------------------------------------

@pytest.mark.parametrize("status", ["available", "used"])
def test_cancelling_removes_access_and_keeps_the_record(cur, status):
    add_access(cur, status=status)

    assert remove_access(cur, 1, DURING) is True
    record = row(cur)
    assert record["access_status"] == "removed"
    assert record["removed_at"] == DURING
    assert record["access_code"] == CODE
    assert record["expires_at"] == END


def test_cancelling_twice_keeps_the_first_removed_at(cur):
    add_access(cur)
    remove_access(cur, 1, DURING)

    assert remove_access(cur, 1, DURING + timedelta(minutes=5)) is False
    assert row(cur)["removed_at"] == DURING


def test_cancelling_without_an_access_record_creates_nothing(cur):
    assert remove_access(cur, 42, DURING) is False
    assert row(cur, 42) is None


# --- Expiry ---------------------------------------------------------------

@pytest.mark.parametrize("status", ["available", "used"])
def test_reading_overdue_access_marks_it_expired(cur, status):
    add_access(cur, status=status)

    assert get_access(cur, 1, END)["access_status"] == "expired"


def test_reading_access_before_expiry_changes_nothing(cur):
    add_access(cur)

    assert get_access(cur, 1, DURING)["access_status"] == "available"


def test_the_sweep_expires_every_overdue_record_and_counts_them(cur):
    add_access(cur, booking_id=1, code="aaaa0001")
    add_access(cur, booking_id=2, code="aaaa0002", status="used")
    add_access(cur, booking_id=3, code="aaaa0003", status="removed")
    add_access(cur, booking_id=4, code="aaaa0004",
               start=END, end=END + timedelta(hours=2))  # not overdue yet

    assert expire_overdue(cur, END) == 2
    assert row(cur, 1)["access_status"] == "expired"
    assert row(cur, 2)["access_status"] == "expired"
    assert row(cur, 3)["access_status"] == "removed"
    assert row(cur, 4)["access_status"] == "available"


# --- Purchase changes the booking interval --------------------------------

def test_changing_the_interval_updates_the_times(cur):
    add_access(cur)
    new_start, new_end = START + timedelta(hours=1), END + timedelta(hours=1)

    assert change_interval(cur, 1, new_start, new_end) is True
    record = row(cur)
    assert record["booked_start_time"] == new_start
    assert record["booked_end_time"] == new_end
    assert record["expires_at"] == new_end


def test_changing_the_interval_of_removed_access_is_refused(cur):
    add_access(cur, status="removed")

    assert change_interval(cur, 1, START, END + timedelta(hours=3)) is False
    assert row(cur)["expires_at"] == END


def test_moving_expiry_later_does_not_un_expire(cur):
    # open decision: an expired record stays expired
    add_access(cur, status="expired")

    change_interval(cur, 1, START, END + timedelta(hours=3))

    assert row(cur)["access_status"] == "expired"