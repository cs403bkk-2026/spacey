"""Keep the old Purchase tables a copy of the service's data (PUR-023).

With PURCHASE_URL set, the service owns every row. After each write the
service answered with success, the wrapper calls the function here with the
service's row, and the same change goes into the old tables, in today's shape
and with the service's id, for the code we don't control: the foreign key
of Access's codes into bookings, other teams' data copies, and Grafana. The
old tables refuse every other write (spacey-purchase scripts/freeze.sql):
each write here sets the mirror flag (SET LOCAL purchase.mirror = 'on', for
its transaction only), which the trigger lets through. A failure is logged,
never raised: the service has already committed, and
`copy_from_spacey.py OLD NEW --repair` fixes the rows.
"""

import threading

import psycopg
from flask import current_app
from werkzeug.security import generate_password_hash

from shared.logger import logger

BOOKING = ("id", "space_id", "member", "paid", "start_time", "end_time",
           "amount_cents", "user_id", "card_last4", "created_at")
SPACE = ("id", "name", "capacity", "price_cents")

# ponytail: one connection, one write at a time. Not app.db: it is shared by
# every request thread in autocommit, so a transaction there could take in
# another thread's statements.
_lock = threading.Lock()
_conn = None


def _write(what, *statements):
    """Run the statements in one transaction the old tables' trigger lets pass."""
    global _conn
    try:
        with _lock:
            for attempt in (1, 2):
                if _conn is None or _conn.closed:
                    _conn = psycopg.connect(
                        current_app.config["DATABASE_URL"], autocommit=True)
                try:
                    with _conn.transaction():
                        _conn.execute("SET LOCAL purchase.mirror = 'on'")
                        for sql, params in statements:
                            _conn.execute(sql, params)
                    return
                except psycopg.OperationalError:
                    # A connection the server dropped (restart) is found dead
                    # only on use: reopen it once. Every write here is
                    # idempotent, so a repeat after a lost COMMIT is harmless.
                    if attempt == 2 or not _conn.closed:
                        raise
    except Exception as error:  # never fail a request the service committed
        # The type only: a database error's text can carry row values.
        logger.error("purchase mirror failed: %s (%s)", what, type(error).__name__)


def _upsert(table, columns, row):
    names = ", ".join(columns)
    values = ", ".join(f"%({c})s" for c in columns)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns[1:])
    return (f"INSERT INTO {table} ({names}) VALUES ({values}) "
            f"ON CONFLICT (id) DO UPDATE SET {sets}", row)


def booking(row):
    """A booking the service created or confirmed: its row, paid or unpaid.
    An unpaid row on the same slot first goes: the service has expired it, and
    old's overlap constraint counts every row. A paid one never goes: then the
    insert fails, is logged, and --repair decides."""
    _write(
        f"booking {row['id']}",
        ("DELETE FROM bookings WHERE space_id = %(space_id)s AND id <> %(id)s "
         "AND NOT paid AND start_time < %(end_time)s AND end_time > %(start_time)s",
         row),
        _upsert("bookings", BOOKING, row),
    )


def cancel(booking_id):
    """Cancelled: the row goes, as today (its access code goes with it)."""
    _write(f"cancel {booking_id}",
           ("DELETE FROM bookings WHERE id = %s", (booking_id,)))


def user(row, password):
    """The service keeps its own hash; this one is of the same password."""
    _write(f"user {row['id']}",
           ("INSERT INTO users (id, email, password_hash) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (row["id"], row["email"], generate_password_hash(password))))


def space(row):
    """A space the service created or changed."""
    _write(f"space {row['id']}", _upsert("spaces", SPACE, row))


def delete_space(space_id):
    _write(f"delete space {space_id}",
           ("DELETE FROM spaces WHERE id = %s", (space_id,)))
