import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

import psycopg
import pytest
from psycopg.errors import ReadOnlySqlTransaction
from psycopg.rows import dict_row
from test_client import BOOKING, SPACE, USER, closed_port_url, err, stub  # noqa: F401 (PUR-022)
from test_switch import VALID_CARD, hub  # noqa: F401 (hub is a fixture)
from werkzeug.security import check_password_hash

import purchase.booking
import purchase.member
import purchase.space
from purchase import client, mirror
from purchase.booking import BOOKING_COLUMNS

PAID = {**BOOKING, "paid": True, "card_last4": "4242"}
# /pay asks check_payable before the card is charged (PUR-021).
PAYABLE = {"id": 1, "amount_cents": 2500, "status": "pending"}
WINDOW = {"start_time": BOOKING["start_time"], "end_time": BOOKING["end_time"]}
LOG = "purchase mirror failed: %s (%s)"

# spacey-purchase scripts/freeze.sql and unfreeze.sql, as of commit 47cb13e
FREEZE = """\
-- Refuse every write to spacey's old Purchase tables, except in a transaction
-- that ran SET LOCAL purchase.mirror = 'on'. Safe to run twice.
CREATE OR REPLACE FUNCTION purchase_refuse_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('purchase.mirror', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'purchase: % on % refused: table frozen', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'read_only_sql_transaction';
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['users', 'spaces', 'bookings'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS purchase_frozen ON %I', t);
        EXECUTE format('DROP TRIGGER IF EXISTS purchase_frozen_truncate ON %I', t);
        EXECUTE format('CREATE TRIGGER purchase_frozen BEFORE INSERT OR UPDATE OR DELETE ON %I'
                       ' FOR EACH ROW EXECUTE FUNCTION purchase_refuse_write()', t);
        EXECUTE format('CREATE TRIGGER purchase_frozen_truncate BEFORE TRUNCATE ON %I'
                       ' FOR EACH STATEMENT EXECUTE FUNCTION purchase_refuse_write()', t);
    END LOOP;
END $$;
"""
UNFREEZE = """\
-- Remove the freeze that freeze.sql adds, so the old tables take every write
-- again. Safe to run twice.
DROP TRIGGER IF EXISTS purchase_frozen ON users;
DROP TRIGGER IF EXISTS purchase_frozen_truncate ON users;
DROP TRIGGER IF EXISTS purchase_frozen ON spaces;
DROP TRIGGER IF EXISTS purchase_frozen_truncate ON spaces;
DROP TRIGGER IF EXISTS purchase_frozen ON bookings;
DROP TRIGGER IF EXISTS purchase_frozen_truncate ON bookings;
DROP FUNCTION IF EXISTS purchase_refuse_write();
"""


def old(sql, params=None):
    """Run one statement on the hub's database, outside the mirror."""
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                         autocommit=True) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None


def old_ids():
    return [r["id"] for r in old("SELECT id FROM bookings ORDER BY id")]


def old_unpaid(booking_id, space_id=1, start="%(s)s", end="%(e)s", paid=False):
    old("INSERT INTO bookings (id, space_id, member, paid, start_time, end_time, "
        f"amount_cents) VALUES (%(id)s, %(sp)s, 'x', %(paid)s, {start}, {end}, 2500)",
        {"id": booking_id, "sp": space_id, "paid": paid,
         "s": BOOKING["start_time"], "e": BOOKING["end_time"]})


@pytest.fixture(autouse=True)
def fresh_mirror_connection():
    mirror._conn = None
    yield
    if mirror._conn is not None and not mirror._conn.closed:
        mirror._conn.close()
    mirror._conn = None


@pytest.fixture
def old_user(hub):  # BOOKING's user_id 1: old bookings.user_id references users
    old("INSERT INTO users (id, email, password_hash) VALUES (1, 'annabel@example.com', 'x')")


@pytest.fixture
def frozen():  # list it after `hub`: hub's reset truncates, which the freeze refuses
    old(FREEZE)
    yield
    old(UNFREEZE)


@pytest.fixture
def writes(monkeypatch):  # records the mirror's writes instead of running them
    calls = []
    monkeypatch.setattr(mirror, "_write", lambda *args: calls.append(args))
    return calls


@pytest.fixture
def errors(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror.logger, "error", lambda *args: calls.append(args))
    return calls


def book(hub):
    return hub.post("/spaces/1/bookings", json=WINDOW)


def pay(hub, stub):
    stub.answer("GET", "/bookings/1", 200, BOOKING)
    stub.answer("GET", "/bookings/1/payable", 200, PAYABLE)
    stub.answer("POST", "/bookings/1/paid", 200, PAID)
    return hub.post("/bookings/1/pay", json=VALID_CARD)


def test_book_pay_cancel_reach_the_frozen_table(
        stub, hub, old_user, frozen, monkeypatch):
    monkeypatch.setattr("app.refund_payment", lambda conn, **kwargs: None)
    seq_before = old("SELECT last_value, is_called FROM bookings_id_seq")
    stub.answer("POST", "/spaces/1/bookings", 201, BOOKING)

    assert book(hub).status_code == 201
    assert old(f"SELECT {BOOKING_COLUMNS} FROM bookings ORDER BY id") == [
        client.booking_row(BOOKING)]

    assert pay(hub, stub).status_code == 200
    row = old(f"SELECT {BOOKING_COLUMNS} FROM bookings")[0]
    assert (row["paid"], row["card_last4"]) == (True, "4242")

    old("INSERT INTO access (booking_id, access_code) VALUES (1, 'test-code-123')")
    with pytest.raises(ReadOnlySqlTransaction):
        old("DELETE FROM bookings WHERE id = 1")

    stub.answer("DELETE", "/bookings/1", 200, PAID)
    assert hub.delete("/bookings/1").status_code == 200
    assert old_ids() == []
    assert old("SELECT * FROM access WHERE booking_id = 1") == []
    assert old("SELECT last_value, is_called FROM bookings_id_seq") == seq_before


def test_user_and_space_writes_reach_the_frozen_tables(stub, hub, frozen):
    stub.answer("POST", "/register", 201, {**USER, "id": 7})
    assert hub.post("/register", json={
        "email": USER["email"], "password": "hunter22"}).status_code == 201
    user = old("SELECT * FROM users WHERE id = 7")[0]
    assert user["email"] == USER["email"]
    assert check_password_hash(user["password_hash"], "hunter22")

    space = {**SPACE, "id": 5}
    stub.answer("POST", "/spaces", 201, space)
    assert hub.post("/spaces", json={"name": "Desk", "capacity": 1}).status_code == 201
    assert old("SELECT * FROM spaces WHERE id = 5") == [space]

    renamed = {**space, "name": "Renamed"}
    stub.answer("PATCH", "/spaces/5", 200, renamed)
    assert hub.patch("/spaces/5", json={"name": "Renamed"}).status_code == 200
    assert old("SELECT * FROM spaces WHERE id = 5") == [renamed]

    stub.answer("DELETE", "/spaces/5", 204, None)
    assert hub.delete("/spaces/5").status_code == 204
    assert old("SELECT * FROM spaces WHERE id = 5") == []


START = datetime.fromisoformat(BOOKING["start_time"])
REFUSED = [
    (lambda: purchase.booking.create_booking(
        None, 1, "annabel", START, START + timedelta(hours=1), 1, 1),
     "POST", "/spaces/1/bookings", 409),
    (lambda: purchase.booking.mark_paid(None, 1, "4242"),
     "POST", "/bookings/1/paid", 409),
    (lambda: purchase.member.register_user(None, "a@b.co", "hunter22"),
     "POST", "/register", 409),
    (lambda: purchase.space.delete_space(None, 1), "DELETE", "/spaces/1", 409),
    (lambda: purchase.space.create_space(None, "Desk", 1, 0), "POST", "/spaces", 400),
    (lambda: purchase.space.update_space(None, 1, {"name": "x"}),
     "PATCH", "/spaces/1", 404),
    (lambda: purchase.booking.cancel_booking(None, 1), "DELETE", "/bookings/1", 404),
]


@pytest.mark.parametrize("call,method,path,status", REFUSED,
                         ids=["booking", "pay", "register", "delete_space",
                              "create_space", "update_space", "cancel"])
def test_a_refused_write_is_not_mirrored(stub, writes, call, method, path, status):
    stub.answer(method, path, status, err("refused"))

    call()

    assert writes == []


def test_url_unset_never_mirrors(stub, hub, writes, monkeypatch):
    monkeypatch.delenv("PURCHASE_URL")
    monkeypatch.setattr("app.refund_payment", lambda conn, **kwargs: None)
    start = "2030-01-01T10:00:00Z"
    window = {"start_time": start, "end_time": "2030-01-01T11:00:00Z"}

    assert hub.post("/register", json={
        "email": "a@b.co", "password": "hunter22"}).status_code == 201
    assert hub.post("/spaces", json={
        "name": "Desk", "capacity": 2, "price_cents": 1000}).status_code == 201
    assert hub.patch("/spaces/2", json={"name": "Desk 2"}).status_code == 200
    assert hub.post("/spaces/2/bookings", json=window).status_code == 201
    assert hub.post("/bookings/1/pay", json=VALID_CARD).status_code == 200
    assert hub.delete("/bookings/1").status_code == 200
    assert hub.delete("/spaces/2").status_code == 204
    assert writes == []


def test_an_unpaid_row_on_the_slot_goes_first(stub, hub, old_user):
    old_unpaid(5)
    stub.answer("POST", "/spaces/1/bookings", 201, BOOKING)

    assert book(hub).status_code == 201

    assert old_ids() == [1]


def test_rows_that_do_not_overlap_stay(stub, hub, old_user):
    old("INSERT INTO spaces (id, name, capacity, price_cents) VALUES (2, 'Other', 1, 0)")
    old_unpaid(2, end="%(s)s", start="(%(s)s::timestamptz - interval '1 hour')")
    old_unpaid(3, start="%(e)s", end="(%(e)s::timestamptz + interval '1 hour')")
    old_unpaid(4, space_id=2)
    stub.answer("POST", "/spaces/1/bookings", 201, BOOKING)

    assert book(hub).status_code == 201

    assert old_ids() == [1, 2, 3, 4]


def test_a_late_payment_replaces_a_newer_expired_hold(stub, hub, old_user):
    old_unpaid(9)

    assert pay(hub, stub).status_code == 200

    rows = old("SELECT id, paid FROM bookings")
    assert rows == [{"id": 1, "paid": True}]


def test_a_failed_mirror_write_is_logged_not_raised(stub, hub, old_user, errors):
    old_unpaid(6, paid=True)
    stub.answer("POST", "/spaces/1/bookings", 201, BOOKING)

    assert book(hub).status_code == 201

    assert old_ids() == [6]
    assert errors == [(LOG, "booking 1", "ExclusionViolation")]


def test_the_mirror_uses_its_own_connection_and_reopens_it(
        stub, hub, old_user, errors):
    stub.answer("POST", "/spaces/1/bookings", 201, BOOKING)
    assert book(hub).status_code == 201
    assert mirror._conn is not hub.application.db

    old("DELETE FROM bookings")
    old("SELECT pg_terminate_backend(%s, 5000)", (mirror._conn.info.backend_pid,))  # a restart
    assert book(hub).status_code == 201
    assert old_ids() == [1]

    old("DELETE FROM bookings")
    old("SELECT pg_terminate_backend(%s, 5000)", (mirror._conn.info.backend_pid,))
    port = urlparse(closed_port_url()).port  # that helper returns an HTTP URL
    hub.application.config["DATABASE_URL"] = (
        f"postgresql://spacey:spacey@127.0.0.1:{port}/spacey")
    assert book(hub).status_code == 201
    assert old_ids() == []
    assert errors == [(LOG, "booking 1", "OperationalError")]