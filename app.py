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


def is_valid_price(price) -> bool:
    return isinstance(price, int) and not isinstance(price, bool) and price >= 0


def member_key(name: str) -> str:
    return name.strip().lower()


def is_subscribed(cur, member) -> bool:
    if not isinstance(member, str):
        return False
    cur.execute(
        "SELECT 1 FROM subscriptions WHERE member = %s AND active",
        (member_key(member),),
    )
    return cur.fetchone() is not None


def local_time(value: datetime) -> str:
    """For the HTML pages: Bangkok time, no seconds or offset clutter."""
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


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
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM bookings WHERE paid"
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
        cur.execute(
            "TRUNCATE bookings, spaces, subscriptions RESTART IDENTITY CASCADE"
        )

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

        # Set by the redirect when a form booking fails (see book_from_form);
        # a successful one goes to the confirmation page instead.
        message = ""
        if request.args.get("error"):
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
        if not is_valid_price(price_cents):
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
        if not any(field in body for field in ("name", "capacity", "price_cents")):
            return jsonify(
                error="provide name, capacity and/or price_cents to update"
            ), 400

        with app.db.cursor() as cur:
            cur.execute("SELECT id FROM spaces WHERE id = %s", (space_id,))
            if cur.fetchone() is None:
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

            # COALESCE keeps the current value for fields not in the request
            cur.execute(
                "UPDATE spaces "
                "SET name = COALESCE(%s, name), "
                "capacity = COALESCE(%s, capacity), "
                "price_cents = COALESCE(%s, price_cents) "
                "WHERE id = %s "
                "RETURNING id, name, capacity, price_cents",
                (name, capacity, price_cents, space_id),
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
                "SELECT id, space_id, member, paid, start_time, end_time, amount_cents "
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
                "SELECT id, capacity, price_cents FROM spaces WHERE id = %s",
                (space_id,),
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

            # Unpaid until POST /bookings/<id>/pay is called - unless the
            # member subscribes: then it is paid at once and costs nothing extra.
            subscribed = is_subscribed(cur, member)
            try:
                cur.execute(
                    "INSERT INTO bookings "
                    "(space_id, member, paid, start_time, end_time, amount_cents) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "RETURNING id, space_id, member, paid, start_time, end_time, amount_cents",
                    (
                        space_id,
                        member,
                        subscribed,
                        start_time,
                        end_time,
                        0 if subscribed else space["price_cents"],
                    ),
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

        return redirect(url_for("booking_confirmation", booking_id=payload["id"]))

    @app.get("/bookings/<int:booking_id>/confirmation")
    def booking_confirmation(booking_id):
        """What a member sees after booking: the details, a Pay button and,
        once paid, an Unlock button that shows the access code."""
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT b.id, b.member, b.paid, b.start_time, b.end_time, "
                "b.amount_cents, s.name AS space_name "
                "FROM bookings b JOIN spaces s ON s.id = b.space_id "
                "WHERE b.id = %s",
                (booking_id,),
            )
            booking = cur.fetchone()

        if booking is None:
            return "<p>Booking not found. <a href='/'>Back to spaces</a></p>", 404

        total_display = f"${booking['amount_cents'] / 100:.2f}"

        if booking["paid"]:
            action = f"""
              <p>Paid. Total: {total_display}</p>
              <form method="post" action="/bookings/{booking_id}/confirmation/unlock">
                <button type="submit">Unlock</button>
              </form>
            """
        else:
            action = f"""
              <p>Not paid yet - total {total_display}, pay to get your access code.</p>
              <form method="post" action="/bookings/{booking_id}/confirmation/pay">
                <button type="submit">Pay</button>
              </form>
            """

        message = ""
        if request.args.get("code"):
            message = (
                f"<p>Your access code: <strong>"
                f"{escape(request.args['code'])}</strong></p>"
            )
        elif request.args.get("error"):
            message = f"<p>{escape(request.args['error'])}</p>"

        return f"""
        <html>
          <head><title>Spacey - Booking #{booking_id}</title></head>
          <body>
            <h1>Booking #{booking_id}</h1>
            <p>{escape(booking['space_name'])} for {escape(booking['member'])}</p>
            <p>{local_time(booking['start_time'])}
               to {local_time(booking['end_time'])} (Bangkok time)</p>
            {action}
            {message}
            <p><a href="/">Back to spaces</a></p>
          </body>
        </html>
        """

    @app.post("/bookings/<int:booking_id>/confirmation/pay")
    def pay_from_confirmation(booking_id):
        mark_booking_paid(booking_id)  # mocked payment, same as the API
        return redirect(url_for("booking_confirmation", booking_id=booking_id))

    @app.post("/bookings/<int:booking_id>/confirmation/unlock")
    def unlock_from_confirmation(booking_id):
        payload, status = issue_access_code(booking_id)
        if status >= 400:
            return redirect(
                url_for(
                    "booking_confirmation",
                    booking_id=booking_id,
                    error=payload["error"],
                )
            )
        return redirect(
            url_for(
                "booking_confirmation",
                booking_id=booking_id,
                code=payload["access_code"],
            )
        )

    @app.get("/bookings")
    def list_bookings():
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time, amount_cents "
                "FROM bookings ORDER BY start_time"
            )
            rows = cur.fetchall()

        return jsonify(bookings=[booking_to_json(row) for row in rows])

    @app.get("/bookings/<int:booking_id>")
    def find_booking(booking_id):
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time, amount_cents "
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
                "RETURNING id, space_id, member, paid, start_time, end_time, amount_cents",
                (booking_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(booking_to_json(row))

    def mark_booking_paid(booking_id):
        """Mocked payment: no provider, always succeeds. Paying an
        already-paid booking is a no-op rather than an error, so a retried
        request can't break the flow. Returns the booking, or None."""
        # Mocked payment: no real provider, so it succeeds unless the request
        # body has {"force_failure": true} - that lets us show and test the
        # failure path. Paying an already-paid booking is a no-op rather than
        # an error, so a retried request can't break the flow or charge twice.
        body = request.get_json(silent=True)
        force_failure = isinstance(body, dict) and body.get("force_failure") is True

        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid, start_time, end_time, amount_cents "
                "FROM bookings WHERE id = %s",
                (booking_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None

            if not row["paid"]:
                if force_failure:
                    return {"error": "payment failed"}, 402
                cur.execute(
                    "UPDATE bookings SET paid = TRUE WHERE id = %s "
                    "RETURNING id, space_id, member, paid, start_time, end_time, amount_cents",
                    (booking_id,),
                )
                row = cur.fetchone()

        return row

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

    @app.post("/bookings/<int:booking_id>/pay")
    def pay_booking(booking_id):
        row = mark_booking_paid(booking_id)
        if isinstance(row, tuple):
            payload, status = row
            return jsonify(payload), status
        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(booking_to_json(row))

    @app.post("/bookings/<int:booking_id>/unlock")
    def unlock_booking(booking_id):
        payload, status = issue_access_code(booking_id)
        return jsonify(payload), status

    @app.post("/members/<name>/subscribe")
    def subscribe_member(name):
        # Mocked, like payment: no provider, always succeeds. Subscribing
        # again is a no-op, so a retried request can't break anything.
        member = member_key(name)
        if not member:
            return jsonify(error="member name must not be blank"), 400

        with app.db.cursor() as cur:
            cur.execute(
                "INSERT INTO subscriptions (member) VALUES (%s) "
                "ON CONFLICT (member) DO UPDATE SET active = TRUE "
                "RETURNING member, active, started_at",
                (member,),
            )
            row = cur.fetchone()

        return jsonify(
            member=row["member"],
            active=row["active"],
            started_at=row["started_at"].astimezone(timezone.utc).isoformat(),
        )

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
              <li>Paid bookings: {data['paid_bookings']}</li>
              <li>Unpaid bookings: {data['unpaid_bookings']}</li>
              <li>Members: {data['members']}</li>
              <li>Revenue: {revenue_display}</li>
            </ul>
            <p><a href="/">Back to spaces</a></p>
          </body>
        </html>
        """
    
    return app
app = create_app()
