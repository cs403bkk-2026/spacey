"""PUR-025: the switch row the Purchase team sets, and the freeze it drives."""

import psycopg
import pytest
from test_client import METRICS, closed_port_url, stub  # noqa: F401 (stub is a fixture)
from test_mirror import old
from test_switch import VALID_CARD

import purchase.space
from app import create_app
from purchase import client, mirror

WINDOW = {"start_time": "2030-01-01T10:00:00Z", "end_time": "2030-01-01T11:00:00Z"}


@pytest.fixture
def app_off(monkeypatch):
    """The hub on a fresh database, the URL set, the real switch row. Emptied
    here: reset_on_start would call the service, which is a closed port."""
    monkeypatch.setenv("PURCHASE_URL", closed_port_url())  # any call would fail
    app = create_app(reset_on_start=False)
    old("UPDATE purchase_switch SET state = 'off'")
    old("TRUNCATE access, bookings, spaces, subscriptions, users, payments "
        "RESTART IDENTITY CASCADE")
    with app.db.cursor() as cur:
        purchase.space.seed_starter_space(cur)
    yield app
    old("UPDATE purchase_switch SET state = 'off'")


def set_state(state):
    old("UPDATE purchase_switch SET state = %s", (state,))


def test_the_switch_starts_off_and_takes_three_states(app_off):
    assert old("SELECT state FROM purchase_switch") == [{"state": "off"}]
    with pytest.raises(psycopg.errors.CheckViolation):
        set_state("maybe")
    with pytest.raises(psycopg.errors.UniqueViolation):
        old("INSERT INTO purchase_switch (state) VALUES ('on')")
    create_app(reset_on_start=False)  # a restart keeps the state
    set_state("frozen")
    create_app(reset_on_start=False)
    assert old("SELECT state FROM purchase_switch") == [{"state": "frozen"}]


def test_url_set_but_switch_off_runs_the_old_sql(app_off):
    hub = app_off.test_client()

    booked = hub.post("/spaces/1/bookings", json=WINDOW)
    paid = hub.post(f"/bookings/{booked.get_json()['id']}/pay", json=VALID_CARD)

    assert booked.status_code == 201 and paid.status_code == 200
    assert paid.get_json()["paid"] is True
    assert hub.get("/bookings").status_code == 200
    assert old("SELECT count(*) AS n FROM bookings WHERE paid") == [{"n": 1}]


@pytest.mark.parametrize("state", ["frozen", "on"])
def test_frozen_or_on_refuses_old_writes_but_not_the_mirror(
        app_off, monkeypatch, state):
    monkeypatch.delenv("PURCHASE_URL")  # on without a URL: the lost-URL case
    hub = app_off.test_client()
    booked = hub.post("/spaces/1/bookings", json=WINDOW).get_json()
    set_state(state)

    assert hub.post("/spaces/1/bookings", json={
        "start_time": "2030-01-02T10:00:00Z", "end_time": "2030-01-02T11:00:00Z",
    }).status_code == 503
    assert hub.delete(f"/bookings/{booked['id']}").status_code == 503
    register = {"email": "a@b.co", "password": "hunter22"}
    assert hub.post("/register", json=register).status_code == 503
    assert hub.post(f"/bookings/{booked['id']}/pay", json=VALID_CARD).status_code == 500
    assert hub.get("/bookings").status_code == 200
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        old("TRUNCATE bookings CASCADE")
    with app_off.app_context():
        mirror.cancel(booked["id"])  # sets purchase.mirror: let through
    assert old("SELECT count(*) AS n FROM bookings") == [{"n": 0}]


def test_off_again_lets_old_writes_through(app_off):
    hub = app_off.test_client()
    set_state("frozen")
    set_state("off")

    assert hub.post("/spaces/1/bookings", json=WINDOW).status_code == 201


@pytest.fixture
def logged(monkeypatch):
    lines = []
    for level in ("info", "warning"):
        monkeypatch.setattr(client.logger, level,
                            lambda msg, *args: lines.append(msg % args))
    return lines


@pytest.mark.parametrize("status,line", [
    (200, "purchase service check: ok"),
    (403, "purchase service check: failed (GET /metrics: 403)"),
])
def test_check_link_logs_the_answer(stub, logged, status, line):
    body = METRICS if status == 200 else {"error": "invalid service token"}
    stub.answer("GET", "/metrics", status, body)

    client.check_link()

    assert logged == [line]
    assert stub.requests[0]["authorization"].startswith("Bearer ")


def test_check_link_never_raises(stub, logged, monkeypatch):
    def broken():
        raise RuntimeError("secret detail")
    monkeypatch.setattr(client, "compute_metrics", broken)

    client.check_link()

    assert logged == ["purchase service check: failed (RuntimeError)"]


def test_check_link_without_url_calls_nothing(monkeypatch, logged):
    monkeypatch.delenv("PURCHASE_URL", raising=False)

    client.check_link()

    assert logged == []
