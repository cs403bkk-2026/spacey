"""Access module interface (docs/access-interface.md).

Each test names the rule or term it checks (spacey-business-rules, branch
access/rules-proposal: SP-R10 to SP-R14, SP-T16 to SP-T19).

Phase 0 tests run on today's access table. Phase 1 tests need the access-table
change proposed in the discussion issue (status, used_at, removed_at, no FK);
they skip until those columns exist. Every test also skips until its function
exists in access.py, so this file can be merged before the work it describes.
"""
from datetime import datetime, timedelta, timezone

import pytest

import access

START = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=1)
USED_AT = START + timedelta(minutes=5)
REMOVED_AT = START - timedelta(days=1)
PHASE_1_COLUMNS = {"status", "used_at", "removed_at"}


def need(name):
    """The access function, or skip until it is implemented."""
    fn = getattr(access, name, None)
    if fn is None:
        pytest.skip(f"access.{name} not implemented yet")
    return fn


# ---- fixtures ----------------------------------------------------------------


@pytest.fixture
def cur():
    # Imported here: importing app connects to the database.
    from app import create_app

    app = create_app(reset_on_start=True)
    with app.db.cursor() as cursor:
        yield cursor
    app.db.close()


def insert_booking(cur, paid=True, day=0):
    """A booking row as Purchase would have stored it. Access must not
    depend on how it got there, or on whether it is paid. `day` keeps
    bookings of the same space from overlapping."""
    shift = timedelta(days=day)
    cur.execute(
        "INSERT INTO bookings (space_id, member, paid, start_time, end_time, amount_cents) "
        "VALUES (1, 'member a', %s, %s, %s, 2500) RETURNING id",
        (paid, START + shift, END + shift),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def booking_id(cur):
    return insert_booking(cur)


@pytest.fixture
def phase_1(cur):
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'access'"
    )
    missing = PHASE_1_COLUMNS - {row["column_name"] for row in cur.fetchall()}
    if missing:
        pytest.skip(f"access table lacks {sorted(missing)} (access-table discussion issue)")


def access_rows(cur, booking_id):
    cur.execute("SELECT COUNT(*) AS n FROM access WHERE booking_id = %s", (booking_id,))
    return cur.fetchone()["n"]


class RecordingCursor:
    """Delegates to a real cursor and remembers every SQL statement."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.statements = []

    def execute(self, query, params=None):
        self.statements.append(str(query))
        return self._cursor.execute(query, params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


# ---- phase 0: today's table (JOB-1) -----------------------------------------


def test_sp_r10_grant_access_creates_and_returns_an_access_code(cur, booking_id):
    grant_access = need("grant_access")

    granted = grant_access(cur, booking_id)

    assert granted["booking_id"] == booking_id
    assert granted["access_code"]


def test_sp_r10_granting_twice_returns_the_same_code_and_one_record(cur, booking_id):
    grant_access = need("grant_access")

    first = grant_access(cur, booking_id)
    second = grant_access(cur, booking_id)

    assert second["access_code"] == first["access_code"]
    assert access_rows(cur, booking_id) == 1


def test_sp_r10_access_does_not_check_payment(cur):
    """Purchase decides that the booking is paid; Access only grants."""
    grant_access = need("grant_access")
    unpaid_id = insert_booking(cur, paid=False, day=1)

    assert grant_access(cur, unpaid_id)["access_code"]


def test_sp_t17_access_never_reads_purchase_tables(cur, booking_id):
    grant_access = need("grant_access")
    recording = RecordingCursor(cur)

    grant_access(recording, booking_id)
    for name, args in [("get_access", ()), ("use_access", (USED_AT,)), ("remove_access", (REMOVED_AT,))]:
        fn = getattr(access, name, None)
        if fn is not None:
            fn(recording, booking_id, *args)

    sql = " ".join(recording.statements).lower()
    assert "bookings" not in sql
    assert "spaces" not in sql


def test_get_access_is_none_before_access_is_granted(cur, booking_id):
    get_access = need("get_access")

    assert get_access(cur, booking_id) is None


def test_get_access_returns_the_record_without_changing_it(cur, booking_id):
    get_access = need("get_access")
    granted = need("grant_access")(cur, booking_id)

    first = get_access(cur, booking_id)
    second = get_access(cur, booking_id)

    assert first["access_code"] == granted["access_code"]
    assert second == first


# ---- phase 1: status granted | used | removed --------------------------------


def test_sp_t18_granted_access_has_a_code_and_no_use_yet(cur, booking_id, phase_1):
    granted = need("grant_access")(cur, booking_id)

    assert granted["status"] == "granted"
    assert granted["access_code"]
    assert granted["used_at"] is None
    assert granted["removed_at"] is None


def test_sp_t19_first_use_records_used_and_provides_the_same_code(cur, booking_id, phase_1):
    granted = need("grant_access")(cur, booking_id)

    used = need("use_access")(cur, booking_id, USED_AT)

    assert used["status"] == "used"
    assert used["used_at"] == USED_AT
    assert used["access_code"] == granted["access_code"]


def test_sp_t19_a_later_use_keeps_the_first_use_time(cur, booking_id, phase_1):
    need("grant_access")(cur, booking_id)
    use_access = need("use_access")
    use_access(cur, booking_id, USED_AT)

    again = use_access(cur, booking_id, USED_AT + timedelta(minutes=30))

    assert again["status"] == "used"
    assert again["used_at"] == USED_AT


def test_sp_r10_use_without_an_access_record_grants_and_uses_in_one_step(cur, booking_id, phase_1):
    """A booking paid before access was granted at payment."""
    used = need("use_access")(cur, booking_id, USED_AT)

    assert used["status"] == "used"
    assert used["access_code"]
    assert used["used_at"] == USED_AT
    assert access_rows(cur, booking_id) == 1


def test_sp_r12_removing_granted_access_keeps_the_record_and_its_code(cur, booking_id, phase_1):
    granted = need("grant_access")(cur, booking_id)

    removed = need("remove_access")(cur, booking_id, REMOVED_AT)

    assert removed["status"] == "removed"
    assert removed["removed_at"] == REMOVED_AT
    assert removed["access_code"] == granted["access_code"]
    assert access_rows(cur, booking_id) == 1


def test_sp_r12_removing_used_access_keeps_its_first_use_time(cur, booking_id, phase_1):
    need("grant_access")(cur, booking_id)
    need("use_access")(cur, booking_id, USED_AT)

    removed = need("remove_access")(cur, booking_id, USED_AT + timedelta(hours=1))

    assert removed["status"] == "removed"
    assert removed["used_at"] == USED_AT


def test_sp_r12_removing_twice_keeps_the_first_removal_time(cur, booking_id, phase_1):
    need("grant_access")(cur, booking_id)
    remove_access = need("remove_access")
    remove_access(cur, booking_id, REMOVED_AT)

    again = remove_access(cur, booking_id, REMOVED_AT + timedelta(hours=5))

    assert again["status"] == "removed"
    assert again["removed_at"] == REMOVED_AT


def test_sp_r12_removed_access_is_never_granted_or_used_again(cur, booking_id, phase_1):
    granted = need("grant_access")(cur, booking_id)
    need("remove_access")(cur, booking_id, REMOVED_AT)

    again = need("grant_access")(cur, booking_id)
    used = need("use_access")(cur, booking_id, USED_AT)

    assert again["status"] == "removed"
    assert used["status"] == "removed"
    assert used["used_at"] is None
    assert used["access_code"] == granted["access_code"]


def test_sp_r12_removing_access_that_was_never_granted_changes_nothing(cur, booking_id, phase_1):
    assert need("remove_access")(cur, booking_id, REMOVED_AT) is None
    assert access_rows(cur, booking_id) == 0


def test_sp_r13_removing_access_does_not_touch_the_booking(cur, booking_id, phase_1):
    need("grant_access")(cur, booking_id)
    cur.execute("SELECT * FROM bookings WHERE id = %s", (booking_id,))
    before = cur.fetchone()

    need("remove_access")(cur, booking_id, REMOVED_AT)

    cur.execute("SELECT * FROM bookings WHERE id = %s", (booking_id,))
    assert cur.fetchone() == before


def test_sp_t17_the_access_record_survives_its_booking_being_deleted(cur, booking_id, phase_1):
    """No FK: today's cancel still hard-deletes the booking row."""
    need("grant_access")(cur, booking_id)
    need("remove_access")(cur, booking_id, REMOVED_AT)

    cur.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))

    assert access_rows(cur, booking_id) == 1


def test_the_schema_change_is_safe_to_run_again(cur, phase_1):
    """get_connection() runs the DDL on every start; it must not rewrite
    states or times recorded since the first start."""
    from app import create_app

    granted_id, used_id = insert_booking(cur, day=1), insert_booking(cur, day=2)
    need("grant_access")(cur, granted_id)
    need("use_access")(cur, used_id, USED_AT)

    restarted = create_app(reset_on_start=False)
    with restarted.db.cursor() as again:
        again.execute(
            "SELECT booking_id, status, used_at FROM access ORDER BY booking_id"
        )
        rows = {r["booking_id"]: (r["status"], r["used_at"]) for r in again.fetchall()}
    restarted.db.close()

    assert rows[granted_id] == ("granted", None)
    assert rows[used_id] == ("used", USED_AT)
