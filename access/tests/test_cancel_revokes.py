"""DELETE /bookings/{id} with ACCESS_URL set (extract F3): after Purchase
cancels, the hub asks spacey-access to revoke the code. The cancel answer
never depends on Access. Unit tests: the service is stubbed at access.functions."""

import logging

import pytest

from access import client, functions
from app import create_app

CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}
_slot = iter(range(10, 99))


def booking(app, paid=True):
    c = app.test_client()
    hour = next(_slot) % 10 + 8
    day = next(_slot) % 20 + 1
    b = c.post("/spaces/1/bookings", json={
        "member": "annabel",
        "start_time": f"2030-02-{day:02d}T{hour:02d}:00:00+00:00",
        "end_time": f"2030-02-{day:02d}T{hour:02d}:30:00+00:00",
    }).get_json()
    if paid:
        assert c.post(f"/bookings/{b['id']}/pay", json=CARD).status_code == 200
    return b


@pytest.fixture()
def logs(caplog):
    """shared.logger doesn't propagate, so hand caplog's handler to it directly."""
    from shared.logger import logger
    caplog.set_level(logging.DEBUG)
    logger.addHandler(caplog.handler)
    yield caplog
    logger.removeHandler(caplog.handler)


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("ACCESS_URL", "http://access.test")
    return create_app(reset_on_start=True)


@pytest.mark.parametrize(("answer", "outcome"), [
    (({"status": "revoked"}, 200), "revoked"),
    (({"error": "access record not found"}, 404), "no_access"),
    (({"error": "access is used and cannot be revoked", "status": "used"}, 409), "final_state"),
])
def test_cancel_revokes_and_answers_as_before(app, monkeypatch, logs, answer, outcome):
    b = booking(app)
    calls = []
    monkeypatch.setattr(functions, "revoke_access", lambda bid: calls.append(bid) or answer)

    response = app.test_client().delete(f"/bookings/{b['id']}")

    assert response.status_code == 200
    assert response.get_json()["id"] == b["id"]
    assert calls == [b["id"]]
    assert f"outcome={outcome}" in logs.text


def test_access_down_never_changes_the_cancel(app, monkeypatch, logs):
    b = booking(app)

    def down(bid):
        raise client.AccessUnavailable("POST /bookings/1/access/revoke: URLError")

    monkeypatch.setattr(functions, "revoke_access", down)
    response = app.test_client().delete(f"/bookings/{b['id']}")

    assert response.status_code == 200
    assert "outcome=unavailable" in logs.text


def test_unknown_booking_never_reaches_access(app, monkeypatch):
    monkeypatch.setattr(functions, "revoke_access",
                        lambda bid: (_ for _ in ()).throw(AssertionError("Access was called")))

    assert app.test_client().delete("/bookings/999999").status_code == 404


def test_without_access_url_cancel_makes_no_call(monkeypatch):
    monkeypatch.delenv("ACCESS_URL", raising=False)
    app = create_app(reset_on_start=True)
    b = booking(app)
    monkeypatch.setattr(functions, "revoke_access",
                        lambda bid: (_ for _ in ()).throw(AssertionError("Access was called")))

    assert app.test_client().delete(f"/bookings/{b['id']}").status_code == 200
