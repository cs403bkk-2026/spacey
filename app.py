import os
import secrets
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify, request
from markupsafe import escape
from psycopg.errors import ExclusionViolation
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

    cur.execute("SELECT COUNT(*) AS count FROM bookings")
    total_bookings = cur.fetchone()["count"]

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
        "bookings": total_bookings,
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

        items = "".join(
            f"""
            <li>
              {escape(row['name'])} - capacity {row['capacity']},
              ${row['price_cents'] / 100:.2f}
              - {"booked" if row['id'] in booked_ids else "available"}
            </li>
            """
            for row in rows
        )
        return f"""
        <html>
          <head><title>Spacey - Spaces</title></head>
          <body>
            <h1>Spacey</h1>
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
        with app.db.cursor() as cur:
            cur.execute("SELECT id, name, capacity, price_cents FROM spaces")
            rows = cur.fetchall()
            cur.execute(
                "SELECT DISTINCT space_id FROM bookings "
                "WHERE start_time <= now() AND end_time > now()"
            )
            booked_ids = {row["space_id"] for row in cur.fetchall()}

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
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, name, capacity, price_cents FROM spaces WHERE id = %s",
                (space_id,),
            )
            space = cur.fetchone()
            if space is None:
                return jsonify(error="space not found"), 404

            cur.execute(
                "SELECT 1 FROM bookings "
                "WHERE space_id = %s AND start_time <= now() AND end_time > now()",
                (space_id,),
            )
            booked = cur.fetchone() is not None

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

    @app.post("/spaces/<int:space_id>/bookings")
    def create_booking(space_id):
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, capacity FROM spaces WHERE id = %s", (space_id,)
            )
            space = cur.fetchone()
            if space is None:
                return jsonify(error="space not found"), 404

            body = request.get_json(silent=True) or {}
            member = body.get("member", "guest")
            start_time = parse_time(body.get("start_time"))
            end_time = parse_time(body.get("end_time"))
            party_size = body.get("party_size", 1)

            if start_time is None or end_time is None:
                return jsonify(
                    error="start_time and end_time are required "
                    "(ISO 8601 with timezone)"
                ), 400
            if end_time <= start_time:
                return jsonify(error="end_time must be after start_time"), 400
            # bool is a subclass of int in Python, so rule out true/false
            if (
                not isinstance(party_size, int)
                or isinstance(party_size, bool)
                or party_size < 1
            ):
                return jsonify(
                    error="party_size must be a whole number of at least 1"
                ), 400
            if party_size > space["capacity"]:
                return jsonify(
                    error=f"party_size {party_size} exceeds this space's "
                    f"capacity of {space['capacity']}"
                ), 400

            # Overlap = starts before the other ends AND ends after the
            # other starts. Back-to-back bookings (10-11, 11-12) are allowed.
            cur.execute(
                "SELECT id FROM bookings "
                "WHERE space_id = %s AND start_time < %s AND end_time > %s",
                (space_id, end_time, start_time),
            )
            if cur.fetchone() is not None:
                return jsonify(
                    error="space is already booked for that time"
                ), 409

            try:
                cur.execute(
                    "INSERT INTO bookings "
                    "(space_id, member, paid, start_time, end_time) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "RETURNING id, space_id, member, paid, start_time, end_time",
                    # unpaid until POST /bookings/<id>/pay is called
                    (space_id, member, False, start_time, end_time),
                )
            except ExclusionViolation:
                # The pre-check above already caught this in the common
                # case; this only fires when two requests raced past it.
                return jsonify(
                    error="space is already booked for that time"
                ), 409
            row = cur.fetchone()

        return jsonify(booking_to_json(row)), 201

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
        # Mocked payment: no real provider, it always succeeds. Paying an
        # already-paid booking is a no-op rather than an error, so a
        # retried request can't break the flow.
        with app.db.cursor() as cur:
            cur.execute(
                "UPDATE bookings SET paid = TRUE WHERE id = %s "
                "RETURNING id, space_id, member, paid, start_time, end_time",
                (booking_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify(error="booking not found"), 404

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
