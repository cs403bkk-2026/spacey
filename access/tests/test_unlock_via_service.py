"""POST /bookings/{id}/unlock with ACCESS_URL set (extract F2): the code comes
from spacey-access, and the answer is still exactly what openapi.yaml promises.

The service is stubbed at access.functions (unit, CI-safe); the real service
is exercised by spacey-access/orchestration (local only)."""

import pytest

from access import client, functions
from app import create_app

CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}
SERVICE_RECORD = {"booking_id": 1, "access_code": "3f9a0c1b", "status": "available",
                  "expires_at": "2030-01-01T11:00:00+00:00", "checked_in_at": None,
                  "checked_out_at": None, "revoked_at": None, "expired_at": None}


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("ACCESS_URL", "http://access.test")
    return create_app(reset_on_start=True)


def paid_booking(app):
    c = app.test_client()
    booking = c.post("/spaces/1/bookings", json={
        "member": "annabel",
        "start_time": "2030-01-01T10:00:00+00:00",
        "end_time": "2030-01-01T11:00:00+00:00",
    }).get_json()
    assert c.post(f"/bookings/{booking['id']}/pay", json=CARD).status_code == 200
    return booking


def test_unlock_asks_the_service_with_the_booking_times(app, monkeypatch):
    booking = paid_booking(app)
    sent = []

    def create(booking_id, start, end):
        sent.append((booking_id, start.isoformat(), end.isoformat()))
        return {**SERVICE_RECORD, "booking_id": booking_id}, 201

    monkeypatch.setattr(functions, "create_access", create)
    response = app.test_client().post(f"/bookings/{booking['id']}/unlock")

    assert response.status_code == 200
    assert response.get_json() == {"booking_id": booking["id"], "access_code": "3f9a0c1b"}
    assert sent == [(booking["id"], "2030-01-01T10:00:00+00:00", "2030-01-01T11:00:00+00:00")]


def test_a_repeat_unlock_is_200_with_the_same_code(app, monkeypatch):
    booking = paid_booking(app)
    answers = iter([({**SERVICE_RECORD}, 201), ({**SERVICE_RECORD}, 200)])
    monkeypatch.setattr(functions, "create_access", lambda *a: next(answers))
    c = app.test_client()

    first = c.post(f"/bookings/{booking['id']}/unlock")
    second = c.post(f"/bookings/{booking['id']}/unlock")

    assert first.status_code == second.status_code == 200
    assert first.get_json()["access_code"] == second.get_json()["access_code"]


def test_unpaid_and_unknown_never_reach_the_service(app, monkeypatch):
    def must_not_call(*a):
        raise AssertionError("Access was called")

    monkeypatch.setattr(functions, "create_access", must_not_call)
    c = app.test_client()
    unpaid = c.post("/spaces/1/bookings", json={
        "member": "x", "start_time": "2030-01-02T10:00:00+00:00",
        "end_time": "2030-01-02T11:00:00+00:00"}).get_json()

    assert c.post(f"/bookings/{unpaid['id']}/unlock").status_code == 402
    assert c.post("/bookings/999999/unlock").status_code == 404


@pytest.mark.parametrize("failure", [
    client.AccessUnavailable("POST /bookings/1/access: 503"),
    client.AccessUnavailable("POST /bookings/1/access: URLError"),
], ids=["service-5xx", "unreachable"])
def test_access_down_is_503_never_500(app, monkeypatch, failure):
    booking = paid_booking(app)

    def down(*a):
        raise failure

    monkeypatch.setattr(functions, "create_access", down)
    response = app.test_client().post(f"/bookings/{booking['id']}/unlock")

    assert response.status_code == 503
    assert response.get_json() == {"error": "access unavailable"}


def test_a_400_from_the_service_is_503_not_passed_through(app, monkeypatch):
    booking = paid_booking(app)
    monkeypatch.setattr(functions, "create_access",
                        lambda *a: ({"error": "end_time must be after start_time"}, 400))

    response = app.test_client().post(f"/bookings/{booking['id']}/unlock")

    assert response.status_code == 503  # the frozen contract has no 400 for unlock


def test_without_access_url_unlock_uses_the_local_table(monkeypatch):
    monkeypatch.delenv("ACCESS_URL", raising=False)
    app = create_app(reset_on_start=True)
    booking = paid_booking(app)
    monkeypatch.setattr(functions, "create_access",
                        lambda *a: (_ for _ in ()).throw(AssertionError("Access was called")))

    response = app.test_client().post(f"/bookings/{booking['id']}/unlock")

    assert response.status_code == 200
    assert set(response.get_json()) == {"booking_id", "access_code"}
