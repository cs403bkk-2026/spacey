import os
import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from flask import Flask, jsonify, redirect, request, url_for
from markupsafe import escape
from psycopg.errors import DeadlockDetected, ExclusionViolation
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://spacey:spacey@localhost:5432/spacey"
)


def get_connection(database_url: str) -> psycopg.Connection:
    conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
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
        # Added after the table already existed, so ALTER instead of editing
        # CREATE TABLE above - existing databases get the new columns too.
        cur.execute(
            "ALTER TABLE bookings "
            "ADD COLUMN IF NOT EXISTS start_time TIMESTAMPTZ, "
            "ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ"
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


def booked_space_ids(cur, window) -> set:
    """Spaces booked during the window, or booked right now if no window."""
    if window is None:
        cur.execute(
            "SELECT DISTINCT space_id FROM bookings "
            "WHERE start_time <= now() AND end_time > now()"
        )
    else:
        start_time, end_time = window
        # Same overlap rule as booking creation: back-to-back is not a clash.
        cur.execute(
            "SELECT DISTINCT space_id FROM bookings "
            "WHERE start_time < %s AND end_time > %s",
            (end_time, start_time),
        )
    return {row["space_id"] for row in cur.fetchall()}


LOCAL_TZ = timezone(timedelta(hours=7))  # Bangkok, no daylight saving


def parse_form_time(value) -> datetime | None:
    """The browser's datetime-local field sends no timezone (2026-09-25T09:00),
    so times typed into the booking form are read as Bangkok time."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed


def is_valid_name(name) -> bool:
    return isinstance(name, str) and name.strip() != ""


def is_valid_capacity(capacity) -> bool:
    # bool is a subclass of int in Python, so rule out true/false
    return (
        isinstance(capacity, int)
        and not isinstance(capacity, bool)
        and capacity >= 1
    )


def booking_to_json(row: dict) -> dict:
    return {
        **row,
        "start_time": row["start_time"].astimezone(timezone.utc).isoformat(),
        "end_time": row["end_time"].astimezone(timezone.utc).isoformat(),
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
        "SELECT COALESCE(SUM(s.price_cents), 0) AS total "
        "FROM bookings b JOIN spaces s ON s.id = b.space_id "
        "WHERE b.paid"
    )
    revenue_cents = cur.fetchone()["total"]

    return {
        "spaces": total_spaces,
        "bookings": booking_counts["total"],
        "paid_bookings": booking_counts["paid"],
        "unpaid_bookings": booking_counts["unpaid"],
        "members": total_members,
        "revenue_cents": revenue_cents,
    }

def reset_tables(conn: psycopg.Connection) -> None:
    """Wipe all rows and restart ids. Only used for tests and an opt-in
    local reset (RESET_DB_ON_START=true) - off by default, so a real
    deployment's data survives an app restart."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE bookings, spaces RESTART IDENTITY CASCADE")

def seed_starter_space(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM spaces")
        if cur.fetchone()["count"] == 0:
            cur.execute(
                "INSERT INTO spaces (name, capacity) VALUES (%s, %s)",
                ("Founders Desk", 1),
            )

def create_app(
    database_url: str = DATABASE_URL, reset_on_start: bool | None = None
) -> Flask:
    if reset_on_start is None:
        reset_on_start = os.getenv("RESET_DB_ON_START", "false").lower() == "true"

    app = Flask(__name__)
    app.db = get_connection(database_url)
    if reset_on_start:
        reset_tables(app.db)
    seed_starter_space(app.db)

    @app.get("/")
    def index():
        with app.db.cursor() as cur:
            cur.execute("SELECT id, name, capacity, price_cents FROM spaces")
            rows = cur.fetchall()
            cur.execute(
                "SELECT DISTINCT space_id FROM bookings "
                "WHERE start_time <= now() AND end_time > now()"
            )
            booked_ids = {row["space_id"] for row in cur.fetchall()}

        def booking_form(space_id):
            return f"""
              <form method="post" action="/spaces/{space_id}/book">
                <input name="member" placeholder="Your name" required>
                <input type="datetime-local" name="start_time" required>
                <input type="datetime-local" name="end_time" required>
                <button type="submit">Book</button>
              </form>
            """

        items = "".join(
            f"""
            <li>
              {escape(row['name'])} - capacity {row['capacity']},
              ${row['price_cents'] / 100:.2f}
              - {"booked" if row['id'] in booked_ids else "available"}
              {"" if row['id'] in booked_ids else booking_form(row['id'])}
            </li>
            """
            for row in rows
        )

        # Set by the redirect after the form posts (see book_from_form)
        message = ""
        if request.args.get("booked"):
            message = (
                f"<p>Booked! Booking #{escape(request.args['booked'])} - "
                f"not paid yet.</p>"
            )
        elif request.args.get("error"):
            message = f"<p>Could not book: {escape(request.args['error'])}</p>"

        return f"""
        <html>
          <head><title>Spacey - Spaces</title></head>
          <body>
            <h1>Spacey</h1>
            {message}
            <p>Times are Bangkok time (UTC+7).</p>
            <ul>{items}</ul>
            <p><a href="/dashboard">View business metrics</a></p>
          </body>
        </html>
        """

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
            cur.execute("SELECT id, name, capacity, price_cents FROM spaces")
            rows = cur.fetchall()
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
        if not isinstance(price_cents, int) or price_cents < 0:
            return jsonify(
                error="price_cents must be a non-negative integer"
            ), 400

        with app.db.cursor() as cur:
            cur.execute(
                "INSERT INTO spaces (name, capacity, price_cents) VALUES (%s, %s, %s) "
                "RETURNING id",
                (name, capacity, price_cents),
            )
            new_id = cur.fetchone()["id"]

        return jsonify(id=new_id, name=name, capacity=capacity, price_cents=price_cents), 201

    @app.get("/spaces/<int:space_id>")
    def get_space(space_id):
        window, error = parse_window(request.args)
        if error:
            return jsonify(error=error), 400

        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, name, capacity, price_cents FROM spaces WHERE id = %s",
                (space_id,),
            )
            space = cur.fetchone()
            if space is None:
                return jsonify(error="space not found"), 404

            booked = space_id in booked_space_ids(cur, window)

        return jsonify({**space, "available": not booked})

    @app.patch("/spaces/<int:space_id>")
    def update_space(space_id):
        body = request.get_json(silent=True) or {}
        if "name" not in body and "capacity" not in body:
            return jsonify(error="provide name and/or capacity to update"), 400

        with app.db.cursor() as cur:
            cur.execute("SELECT id FROM spaces WHERE id = %s", (space_id,))
            if cur.fetchone() is None:
                return jsonify(error="space not found"), 404

            name = body.get("name")
            capacity = body.get("capacity")
            if "name" in body and not is_valid_name(name):
                return jsonify(error="name must not be empty"), 400
            if "capacity" in body and not is_valid_capacity(capacity):
                return jsonify(
                    error="capacity must be a whole number of at least 1"
                ), 400
            if name is not None:
                name = name.strip()

            # COALESCE keeps the current value for fields not in the request
            cur.execute(
                "UPDATE spaces "
                "SET name = COALESCE(%s, name), "
                "capacity = COALESCE(%s, capacity) "
                "WHERE id = %s "
                "RETURNING id, name, capacity, price_cents",
                (name, capacity, space_id),
            )
            space = cur.fetchone()

        return jsonify(space)

    @app.delete("/spaces/<int:space_id>")
    def delete_space(space_id):
        with app.db.cursor() as cur:
            cur.execute("SELECT id FROM spaces WHERE id = %s", (space_id,))
            space = cur.fetchone()
            if space is None:
                return jsonify(error="space not found"), 404

            cur.execute(
                "SELECT id FROM bookings WHERE space_id = %s LIMIT 1",
                (space_id,),
            )
            if cur.fetchone() is not None:
                return jsonify(
                    error="space has bookings, cancel them first"
                ), 409

            cur.execute("DELETE FROM spaces WHERE id = %s", (space_id,))

        return "", 204

    @app.get("/spaces/<int:space_id>/bookings")
    def list_space_bookings(space_id):
        with app.db.cursor() as cur:
            cur.execute("SELECT id FROM spaces WHERE id = %s", (space_id,))
            if cur.fetchone() is None:
                return jsonify(error="space not found"), 404

            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time "
                "FROM bookings WHERE space_id = %s ORDER BY start_time",
                (space_id,),
            )
            rows = cur.fetchall()

        return jsonify(bookings=[booking_to_json(row) for row in rows])

    def book_space(space_id, member, start_time, end_time, party_size):
        """Shared by the JSON API and the HTML booking form.
        Returns (payload, status) - the booking, or an {"error": ...}."""
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, capacity FROM spaces WHERE id = %s", (space_id,)
            )
            space = cur.fetchone()
            if space is None:
                return {"error": "space not found"}, 404

            if end_time <= start_time:
                return {"error": "end_time must be after start_time"}, 400
            # bool is a subclass of int in Python, so rule out true/false
            if (
                not isinstance(party_size, int)
                or isinstance(party_size, bool)
                or party_size < 1
            ):
                return {
                    "error": "party_size must be a whole number of at least 1"
                }, 400
            if party_size > space["capacity"]:
                return {
                    "error": f"party_size {party_size} exceeds this space's "
                    f"capacity of {space['capacity']}"
                }, 400

            # Overlap = starts before the other ends AND ends after the
            # other starts. Back-to-back bookings (10-11, 11-12) are allowed.
            cur.execute(
                "SELECT id FROM bookings "
                "WHERE space_id = %s AND start_time < %s AND end_time > %s",
                (space_id, end_time, start_time),
            )
            if cur.fetchone() is not None:
                return {"error": "space is already booked for that time"}, 409

            try:
                cur.execute(
                    "INSERT INTO bookings "
                    "(space_id, member, paid, start_time, end_time) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "RETURNING id, space_id, member, paid, start_time, end_time",
                    # unpaid until POST /bookings/<id>/pay is called
                    (space_id, member, False, start_time, end_time),
                )
            except (DeadlockDetected, ExclusionViolation):
                # The pre-check above already caught this in the common
                # case; this only fires when two requests raced past it.
                return {"error": "space is already booked for that time"}, 409
            row = cur.fetchone()

        return booking_to_json(row), 201

    @app.post("/spaces/<int:space_id>/bookings")
    def create_booking(space_id):
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
            body.get("member", "guest"),
            start_time,
            end_time,
            body.get("party_size", 1),
        )
        return jsonify(payload), status

    @app.post("/spaces/<int:space_id>/book")
    def book_from_form(space_id):
        """The homepage form posts here, then we send the browser back to
        the space list - with a message, since a form can't read JSON."""
        member = request.form.get("member", "").strip() or "guest"
        start_time = parse_form_time(request.form.get("start_time"))
        end_time = parse_form_time(request.form.get("end_time"))

        if start_time is None or end_time is None:
            return redirect(url_for("index", error="fill in a start and end time"))

        payload, status = book_space(space_id, member, start_time, end_time, 1)
        if status >= 400:
            return redirect(url_for("index", error=payload["error"]))

        return redirect(url_for("index", booked=payload["id"]))

    @app.get("/bookings")
    def list_bookings():
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time "
                "FROM bookings ORDER BY start_time"
            )
            rows = cur.fetchall()

        return jsonify(bookings=[booking_to_json(row) for row in rows])

    @app.get("/bookings/<int:booking_id>")
    def find_booking(booking_id):
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time "
                "FROM bookings WHERE id = %s",
                (booking_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(booking_to_json(row))

    @app.delete("/bookings/<int:booking_id>")
    def cancel_booking(booking_id):
        with app.db.cursor() as cur:
            cur.execute(
                "DELETE FROM bookings WHERE id = %s "
                "RETURNING id, space_id, member, paid, start_time, end_time",
                (booking_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(booking_to_json(row))

    @app.post("/bookings/<int:booking_id>/pay")
    def pay_booking(booking_id):
        # Mocked payment: no real provider, so it succeeds unless the request
        # body has {"force_failure": true} - that lets us show and test the
        # failure path. Paying an already-paid booking is a no-op rather than
        # an error, so a retried request can't break the flow or charge twice.
        body = request.get_json(silent=True)
        force_failure = isinstance(body, dict) and body.get("force_failure") is True

        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time "
                "FROM bookings WHERE id = %s",
                (booking_id,),
            )
            row = cur.fetchone()
            if row is None:
                return jsonify(error="booking not found"), 404

            if not row["paid"]:
                if force_failure:
                    return jsonify(error="payment failed"), 402
                cur.execute(
                    "UPDATE bookings SET paid = TRUE WHERE id = %s "
                    "RETURNING id, space_id, member, paid, start_time, end_time",
                    (booking_id,),
                )
                row = cur.fetchone()

        return jsonify(booking_to_json(row))

    @app.post("/bookings/<int:booking_id>/unlock")
    def unlock_booking(booking_id):
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, paid FROM bookings WHERE id = %s", (booking_id,)
            )
            booking = cur.fetchone()

        if booking is None:
            return jsonify(error="booking not found"), 404

        if not booking["paid"]:
            return jsonify(error="booking is not paid"), 402

        access_code = secrets.token_hex(4)  # mocked lock integration
        return jsonify(booking_id=booking_id, access_code=access_code)

    @app.get("/metrics")
    def metrics():
        with app.db.cursor() as cur:
            data = compute_metrics(cur)

        return jsonify(**data)

    @app.get("/dashboard")
    def dashboard():
        with app.db.cursor() as cur:
            data = compute_metrics(cur)

        revenue_display = f"${data['revenue_cents'] / 100:.2f}"
        return f"""
        <html>
          <head><title>Spacey - Business Metrics</title></head>
          <body>
            <h1>Spacey - Business Metrics</h1>
            <ul>
              <li>Spaces: {data['spaces']}</li>
              <li>Bookings: {data['bookings']}</li>
              <li>Members: {data['members']}</li>
              <li>Revenue: {revenue_display}</li>
            </ul>
            <p><a href="/">Back to spaces</a></p>
          </body>
        </html>
        """
    
    return app
app = create_app()
