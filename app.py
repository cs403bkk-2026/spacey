import os
import secrets

import psycopg
from flask import Flask, jsonify, request
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
    return conn


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
        return "<h1>Spacey</h1><p>The founding team is building here.</p>"

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
            cur.execute("SELECT DISTINCT space_id FROM bookings")
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

        if not name or not isinstance(capacity, int):
            return jsonify(error="name and capacity are required"), 400
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
    
    @app.post("/spaces/<int:space_id>/bookings")
    def create_booking(space_id):
        with app.db.cursor() as cur:
            cur.execute("SELECT id FROM spaces WHERE id = %s", (space_id,))
            space = cur.fetchone()
            if space is None:
                return jsonify(error="space not found"), 404

            cur.execute(
                "SELECT id FROM bookings WHERE space_id = %s", (space_id,)
            )
            if cur.fetchone() is not None:
                return jsonify(error="space is already booked"), 409

            body = request.get_json(silent=True) or {}
            member = body.get("member", "guest")

            cur.execute(
                "INSERT INTO bookings (space_id, member, paid) "
                "VALUES (%s, %s, %s) RETURNING id",
                (space_id, member, True),  # mocked payment: always succeeds
            )
            new_id = cur.fetchone()["id"]
    
        return jsonify(
            id=new_id, space_id=space_id, member=member, paid=True
        ), 201

    @app.get("/bookings/<int:booking_id>")
    def find_booking(booking_id):
        with app.db.cursor() as cur:
            cur.execute(
                "SELECT id, space_id, member, paid FROM bookings "
                "WHERE id = %s",
                (booking_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(row)

    @app.delete("/bookings/<int:booking_id>")
    def cancel_booking(booking_id):
        with app.db.cursor() as cur:
            cur.execute(
                "DELETE FROM bookings WHERE id = %s "
                "RETURNING id, space_id, member, paid",
                (booking_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify(error="booking not found"), 404

        return jsonify(row)

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

        return jsonify(
            spaces=total_spaces,
            bookings=total_bookings,
            members=total_members,
            revenue_cents=revenue_cents,
        )

    return app
app = create_app()
