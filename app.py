import os
import re
import secrets
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify, redirect, request, session
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash

from access import issue_access_code
# Called qualified, since route functions below reuse names like get_space.
import purchase.booking
import purchase.member
import purchase.space
from purchase.member import subscribe
from purchase.space import booked_space_ids, is_valid_capacity, is_valid_name, is_valid_price

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://spacey:spacey@localhost:5432/spacey"
)
# Signs the login session cookie. Fine for local/dev; a real deployment
# must set a real SECRET_KEY (see issue #47), or every restart logs
# everyone out and, worse, an unset default would be a known, public key.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-not-for-production")

# Business metrics now live in Grafana (#207). /dashboard redirects there;
# /metrics (JSON) stays part of the API.
REPORTING_URL = os.getenv(
    "REPORTING_URL", "https://grafana.cs403bkk26.space/d/spacey-reporting"
)


def get_connection(database_url: str) -> psycopg.Connection:
    try:
        conn = psycopg.connect(
            database_url, row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError as error:
        # A raw psycopg traceback here is the first thing a new contributor
        # sees if Postgres isn't running yet - fail fast with a clear pointer
        # instead. See the Configuration section in README.md.
        raise SystemExit(
            f"Could not connect to the database at DATABASE_URL={database_url!r}\n"
            f"{error}\n"
            "Is Postgres running? Try: docker compose up db -d"
        ) from None
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS spaces (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                capacity INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "ALTER TABLE spaces ADD COLUMN IF NOT EXISTS "
            "price_cents INTEGER NOT NULL DEFAULT 0"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                space_id INTEGER NOT NULL REFERENCES spaces (id),
                member TEXT NOT NULL,
                paid BOOLEAN NOT NULL
            )
            """
        )
        # Mocked subscriptions, keyed by the trimmed lower-case member name.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                member TEXT PRIMARY KEY,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                started_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # The access code handed out when a booking is unlocked (#171).
        # One code per booking, kept so a page refresh shows the same code
        # instead of a new one. ON DELETE CASCADE because cancelling a
        # booking deletes its row, and the code is worthless without it.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS access (
                booking_id INTEGER PRIMARY KEY
                    REFERENCES bookings (id) ON DELETE CASCADE,
                access_code TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # First step of #120 (real accounts): just registration for now.
        # Storing only a hash, never the password itself.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Added after the table already existed, so ALTER instead of editing
        # CREATE TABLE above - existing databases get the new columns too.
        cur.execute(
            "ALTER TABLE bookings "
            "ADD COLUMN IF NOT EXISTS start_time TIMESTAMPTZ, "
            "ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ"
        )
        # Price charged at booking time, so a later price change can't rewrite past revenue.
        cur.execute(
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS amount_cents INTEGER"
        )
        # Links a booking to the account that was logged in when it was made
        # (#134, the first concrete step of #86). NULL for a guest booking
        # made while logged out, and for every booking made before this.
        cur.execute(
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS "
            "user_id INTEGER REFERENCES users (id)"
        )
        # Last 4 digits only (#119) - never the full card number or CVC.
        # NULL until the booking is actually paid.
        cur.execute(
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS card_last4 TEXT"
        )
        # When the booking was made (not when the space is used), so the
        # dashboard can show growth over time. Bookings made before this
        # column existed get the time the column was added - the best we
        # have, and it keeps the column NOT NULL.
        cur.execute(
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        )
        # Bookings from before that column existed get the space's current price (best we have).
        cur.execute(
            "UPDATE bookings SET amount_cents = s.price_cents "
            "FROM spaces s "
            "WHERE s.id = bookings.space_id AND bookings.amount_cents IS NULL"
        )
        # Belt-and-suspenders against double-booking: the app already checks
        # for overlaps before inserting, but that check-then-insert isn't
        # atomic, so two simultaneous requests could both pass the check.
        # This constraint makes Postgres itself reject the second insert.
        cur.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'no_overlapping_bookings'
                ) THEN
                    ALTER TABLE bookings
                    ADD CONSTRAINT no_overlapping_bookings
                    EXCLUDE USING gist (
                        space_id WITH =,
                        tstzrange(start_time, end_time) WITH &&
                    );
                END IF;
            END $$;
            """
        )
    return conn


CARD_NUMBER_RE = re.compile(r"^\d{13,19}$")
CVC_RE = re.compile(r"^\d{3,4}$")
EXPIRY_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{2})$")


def validate_card(card_number, expiry, cvc) -> str | None:
    """Returns an error message, or None if the (mocked) card looks valid -
    right shape and not expired, not a real Luhn/network check."""
    if not isinstance(card_number, str) or not CARD_NUMBER_RE.match(card_number):
        return "card_number must be 13-19 digits"
    if not isinstance(cvc, str) or not CVC_RE.match(cvc):
        return "cvc must be 3 or 4 digits"
    if not isinstance(expiry, str):
        return "expiry must be in MM/YY format"
    match = EXPIRY_RE.match(expiry)
    if match is None:
        return "expiry must be in MM/YY format"
    month, year = int(match.group(1)), 2000 + int(match.group(2))
    now = datetime.now(timezone.utc)
    if (year, month) < (now.year, now.month):
        return "card has expired"
    return None


def parse_time(value) -> datetime | None:
    """ISO 8601 with a timezone, e.g. 2026-09-25T09:00:00+07:00."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def parse_window(args) -> tuple[tuple | None, str | None]:
    """Optional ?start_time=&end_time= as (window, error); window is None if absent."""
    raw_start, raw_end = args.get("start_time"), args.get("end_time")
    if raw_start is None and raw_end is None:
        return None, None
    start_time, end_time = parse_time(raw_start), parse_time(raw_end)
    if start_time is None or end_time is None:
        return None, (
            "start_time and end_time must be given together "
            "(ISO 8601 with timezone, e.g. 2026-09-25T09:00:00Z)"
        )
    if end_time <= start_time:
        return None, "end_time must be after start_time"
    return (start_time, end_time), None


def booking_to_json(row: dict) -> dict:
    return {
        **row,
        "start_time": row["start_time"].astimezone(timezone.utc).isoformat(),
        "end_time": row["end_time"].astimezone(timezone.utc).isoformat(),
        "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
    }


def compute_metrics(cur) -> dict:
    cur.execute("SELECT COUNT(*) AS count FROM spaces")
    total_spaces = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS total, "
        "COUNT(*) FILTER (WHERE paid) AS paid, "
        "COUNT(*) FILTER (WHERE NOT paid) AS unpaid "
        "FROM bookings"
    )
    booking_counts = cur.fetchone()

    cur.execute("SELECT COUNT(DISTINCT member) AS count FROM bookings")
    total_members = cur.fetchone()["count"]

    cur.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM bookings WHERE paid"
    )
    revenue_cents = cur.fetchone()["total"]

    # Booked hours over the next 7 days, clipped to that window, across all
    # spaces - same overlap rule used everywhere else (starts before the
    # window ends AND ends after the window starts).
    cur.execute(
        "SELECT COALESCE(SUM(EXTRACT(EPOCH FROM ("
        "LEAST(end_time, now() + interval '7 days') - GREATEST(start_time, now())"
        ")) / 3600.0), 0) AS hours "
        "FROM bookings "
        "WHERE start_time < now() + interval '7 days' AND end_time > now()"
    )
    booked_hours = float(cur.fetchone()["hours"])
    available_hours = total_spaces * 7 * 24
    utilization = booked_hours / available_hours if available_hours > 0 else 0.0

    cur.execute(
        "SELECT COUNT(*) AS count FROM ("
        "SELECT member FROM bookings GROUP BY member HAVING COUNT(*) > 1"
        ") repeat_members"
    )
    repeat_members = cur.fetchone()["count"]
    repeat_member_rate = repeat_members / total_members if total_members > 0 else 0.0

    payment_conversion = (
        booking_counts["paid"] / booking_counts["total"]
        if booking_counts["total"] > 0
        else 0.0
    )

    avg_revenue_cents_per_paid_booking = (
        round(revenue_cents / booking_counts["paid"])
        if booking_counts["paid"] > 0
        else 0
    )

    cur.execute(
        "SELECT s.id, s.name, "
        "COALESCE(SUM(b.amount_cents) FILTER (WHERE b.paid), 0) AS revenue_cents "
        "FROM spaces s LEFT JOIN bookings b ON b.space_id = s.id "
        "GROUP BY s.id, s.name ORDER BY s.id"
    )
    revenue_by_space = cur.fetchall()

    return {
        "spaces": total_spaces,
        "bookings": booking_counts["total"],
        "paid_bookings": booking_counts["paid"],
        "unpaid_bookings": booking_counts["unpaid"],
        "members": total_members,
        "revenue_cents": revenue_cents,
        "utilization": utilization,
        "repeat_member_rate": repeat_member_rate,
        "payment_conversion": payment_conversion,
        "avg_revenue_cents_per_paid_booking": avg_revenue_cents_per_paid_booking,
        "revenue_by_space": revenue_by_space,
    }


def reset_tables(conn: psycopg.Connection) -> None:
    """Wipe all rows and restart ids. Only used for tests and an opt-in
    local reset (RESET_DB_ON_START=true) - off by default, so a real
    deployment's data survives an app restart."""
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE access, bookings, spaces, subscriptions, users "
            "RESTART IDENTITY CASCADE"
        )


def seed_starter_space(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM spaces")
        if cur.fetchone()["count"] == 0:
            cur.execute(
                "INSERT INTO spaces (name, capacity, price_cents) "
                "VALUES (%s, %s, %s)",
                ("Founders Desk", 1, 2500),  # $25.00 per hour
            )


def create_app(
    database_url: str = DATABASE_URL, reset_on_start: bool | None = None
) -> Flask:
    if reset_on_start is None:
        reset_on_start = os.getenv(
            "RESET_DB_ON_START", "false").lower() == "true"

    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.db = get_connection(database_url)
    if reset_on_start:
        reset_tables(app.db)
    seed_starter_space(app.db)

    @app.get("/")
    def index():
        # The browser client lives at /app/ (spacey-frontend). This process
        # is the JSON API.
        return redirect("/app/", code=302)

    @app.post("/register")
    def register():
        body = request.get_json(silent=True) or {}
        with app.db.cursor() as cur:
            payload, status = purchase.member.register_user(
                cur, body.get("email"), body.get("password")
            )
        return jsonify(payload), status


    def login_user(email, password):
        """Returns (payload, status) - {"id": ..., "email": ...}, or an error.
        Wrong password and unknown email give the identical error, so a
        failed attempt can't be used to find out which emails are registered."""
        invalid = {"error": "invalid email or password"}, 401
        if not isinstance(email, str) or not isinstance(password, str):
            return invalid

        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash FROM users WHERE email = %s",
                (email.strip().lower(),),
            )
            user = cur.fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            return invalid

        session["user_id"] = user["id"]
        return {"id": user["id"], "email": user["email"]}, 200

    @app.post("/login")
    def login():
        body = request.get_json(silent=True) or {}
        payload, status = login_user(body.get("email"), body.get("password"))
        return jsonify(payload), status

    @app.post("/logout")
    def logout():
        # Idempotent: logging out when already logged out just does nothing.
        session.pop("user_id", None)
        return jsonify(status="ok")

    @app.get("/health")
    def health():
        try:
            with app.db.cursor() as cur:
                cur.execute("SELECT 1")
        except psycopg.Error:
            return jsonify(status="error", error="database unreachable"), 503

        return jsonify(
            status="ok",
            revision=os.getenv("APP_REVISION", "local"),
        )

    @app.get("/spaces")
    def list_spaces():
        window, error = parse_window(request.args)
        if error:
            return jsonify(error=error), 400

        with app.db.cursor() as cur:
            rows = purchase.space.list_spaces(cur)
            booked_ids = booked_space_ids(cur, window)

        spaces = [
            {**row, "available": row["id"] not in booked_ids} for row in rows
        ]
        return jsonify(spaces=spaces)

    @app.post("/spaces")
    def create_space():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        capacity = body.get("capacity")
        price_cents = body.get("price_cents", 0)

        if name is None or capacity is None:
            return jsonify(error="name and capacity are required"), 400
        if not is_valid_name(name):
            return jsonify(error="name must not be empty"), 400
        if not is_valid_capacity(capacity):
            return jsonify(
                error="capacity must be a whole number of at least 1"
            ), 400
        name = name.strip()
        if not is_valid_price(price_cents):
            return jsonify(
                error="price_cents must be a non-negative integer"
            ), 400

        with app.db.cursor() as cur:
            space = purchase.space.create_space(cur, name, capacity, price_cents)

        return jsonify(space), 201

    @app.get("/spaces/<int:space_id>")
    def get_space(space_id):
        window, error = parse_window(request.args)
        if error:
            return jsonify(error=error), 400

        with app.db.cursor() as cur:
            space = purchase.space.get_space(cur, space_id)
            if space is None:
                return jsonify(error="space not found"), 404

            booked = space_id in booked_space_ids(cur, window)

        return jsonify({**space, "available": not booked})

    @app.patch("/spaces/<int:space_id>")
    def update_space(space_id):
        body = request.get_json(silent=True) or {}
        if not any(field in body for field in ("name", "capacity", "price_cents")):
            return jsonify(
                error="provide name, capacity and/or price_cents to update"
            ), 400

        with app.db.cursor() as cur:
            if purchase.space.get_space(cur, space_id) is None:
                return jsonify(error="space not found"), 404

            name = body.get("name")
            capacity = body.get("capacity")
            price_cents = body.get("price_cents")
            if "name" in body and not is_valid_name(name):
                return jsonify(error="name must not be empty"), 400
            if "capacity" in body and not is_valid_capacity(capacity):
                return jsonify(
                    error="capacity must be a whole number of at least 1"
                ), 400
            if "price_cents" in body and not is_valid_price(price_cents):
                return jsonify(
                    error="price_cents must be a non-negative integer"
                ), 400
            if name is not None:
                name = name.strip()

            space = purchase.space.update_space(cur, space_id, name, capacity, price_cents)

        return jsonify(space)

    @app.delete("/spaces/<int:space_id>")
    def delete_space(space_id):
        with app.db.cursor() as cur:
            payload, status = purchase.space.delete_space(cur, space_id)
        if payload is None:
            return "", status
        return jsonify(payload), status

    @app.get("/spaces/<int:space_id>/bookings")
    def list_space_bookings(space_id):
        with app.db.cursor() as cur:
            if purchase.space.get_space(cur, space_id) is None:
                return jsonify(error="space not found"), 404

            rows = purchase.booking.list_space_bookings(cur, space_id)

        return jsonify(bookings=[booking_to_json(row) for row in rows])

    def book_space(space_id, member, start_time, end_time, party_size):
        """Returns (payload, status) - the booking, or an {"error": ...}."""
        with app.db.cursor() as cur:
            # Linked to the account if one is logged in; NULL for a guest.
            payload, status = purchase.booking.create_booking(
                cur, space_id, member, start_time, end_time, party_size,
                session.get("user_id"),
            )
        if status == 201:
            payload = booking_to_json(payload)
        return payload, status

    @app.post("/spaces/<int:space_id>/bookings")
    def create_booking_from_json(space_id):
        body = request.get_json(silent=True) or {}
        start_time = parse_time(body.get("start_time"))
        end_time = parse_time(body.get("end_time"))

        if start_time is None or end_time is None:
            return jsonify(
                error="start_time and end_time are required "
                "(ISO 8601 with timezone)"
            ), 400

        payload, status = book_space(
            space_id,
            body.get("member"),
            start_time,
            end_time,
            body.get("party_size", 1),
        )
        return jsonify(payload), status

    @app.get("/bookings")
    def list_bookings():
        with app.db.cursor() as cur:
            rows = purchase.booking.list_bookings(cur)

        return jsonify(bookings=[booking_to_json(row) for row in rows])

    @app.get("/me/bookings")
    def list_my_bookings():
        """The logged-in account's bookings, so the client never has to
        fetch everyone's and filter them itself."""
        user_id = session.get("user_id")
        if user_id is None:
            return jsonify(error="log in to see your bookings"), 401

        with app.db.cursor() as cur:
            rows = purchase.booking.list_user_bookings(cur, user_id)

        return jsonify(bookings=[booking_to_json(row) for row in rows])

    @app.get("/bookings/<int:booking_id>")
    def find_booking(booking_id):
        with app.db.cursor() as cur:
            row = purchase.booking.get_booking(cur, booking_id)

        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(booking_to_json(row))

    @app.delete("/bookings/<int:booking_id>")
    def cancel_booking(booking_id):
        with app.db.cursor() as cur:
            row = purchase.booking.cancel_booking(cur, booking_id)

        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(booking_to_json(row))

    def mark_booking_paid(booking_id, card_number, expiry, cvc, force_failure=False):
        """Mocked payment: no provider, so it succeeds unless force_failure
        is set or the card doesn't look valid (see validate_card). Paying an
        already-paid booking is a no-op rather than an error, so a retried
        request can't break the flow or charge twice - and doesn't need a
        card either. Only the card's last 4 digits are ever stored.
        Returns (payload, status) - the booking, or an {"error": ...}."""
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time, "
                "amount_cents, user_id, card_last4, created_at "
                "FROM bookings WHERE id = %s",
                (booking_id,),
            )
            row = cur.fetchone()
            if row is None:
                return {"error": "booking not found"}, 404

            if row["paid"]:
                return booking_to_json(row), 200

            card_error = validate_card(card_number, expiry, cvc)
            if card_error:
                return {"error": card_error}, 400

            if force_failure:
                return {"error": "payment failed"}, 402

            cur.execute(
                "UPDATE bookings SET paid = TRUE, card_last4 = %s WHERE id = %s "
                "RETURNING id, space_id, member, paid, start_time, end_time, "
                "amount_cents, user_id, card_last4, created_at",
                (card_number[-4:], booking_id),
            )
            row = cur.fetchone()

        return booking_to_json(row), 200


    @app.post("/bookings/<int:booking_id>/pay")
    def pay_booking(booking_id):
        body = request.get_json(silent=True) or {}
        payload, status = mark_booking_paid(
            booking_id,
            body.get("card_number"),
            body.get("expiry"),
            body.get("cvc"),
            force_failure=body.get("force_failure") is True,
        )
        return jsonify(payload), status

    @app.post("/bookings/<int:booking_id>/unlock")
    def unlock_booking(booking_id):
        payload, status = issue_access_code(booking_id)
        return jsonify(payload), status

    @app.post("/members/<name>/subscribe")
    def subscribe_member(name):
        with app.db.cursor() as cur:
            payload, status = subscribe(cur, name)
        return jsonify(payload), status

    @app.get("/metrics")
    def metrics():
        with app.db.cursor() as cur:
            data = compute_metrics(cur)

        return jsonify(**data)

    @app.get("/dashboard")
    def dashboard():
        # A temporary redirect, so bookmarks follow the dashboard and rolling back
        # this change is not undone by a browser's cached permanent redirect.
        return redirect(REPORTING_URL, code=302)

    return app


app = create_app()
