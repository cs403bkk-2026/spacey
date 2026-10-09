from unittest.mock import MagicMock, patch

from app import create_app
from access import issue_access_code


def make_app():
    return create_app(reset_on_start=True)


def test_issue_access_code_never_reads_bookings():
    """Access only writes its own table; Purchase decides who may unlock."""
    cur = MagicMock()
    cur.fetchone.return_value = {"access_code": "a3f9c21b"}
    fake_app = MagicMock()
    fake_app.db.cursor.return_value.__enter__.return_value = cur

    with patch("access.service.app", fake_app):
        payload, status = issue_access_code(7)

    assert status == 200
    assert payload == {"booking_id": 7, "access_code": "a3f9c21b"}
    statements = [call.args[0] for call in cur.execute.call_args_list]
    assert statements, "expected Access to run its own INSERT"
    assert all("FROM bookings" not in sql for sql in statements)


def test_issue_access_code_returns_a_code():
    app = make_app()
    app.test_client().post(
        "/spaces/1/bookings",
        json={
            "member": "annabel",
            "start_time": "2030-01-01T10:00:00+00:00",
            "end_time": "2030-01-01T11:00:00+00:00",
        },
    )

    with app.app_context():
        payload, status = issue_access_code(1)

    assert status == 200
    assert payload["booking_id"] == 1
    assert len(payload["access_code"]) > 0


def test_issuing_twice_returns_the_same_code():
    app = make_app()
    app.test_client().post(
        "/spaces/1/bookings",
        json={
            "member": "annabel",
            "start_time": "2030-01-01T10:00:00+00:00",
            "end_time": "2030-01-01T11:00:00+00:00",
        },
    )

    with app.app_context():
        first, _ = issue_access_code(1)
        second, _ = issue_access_code(1)

    assert first["access_code"] == second["access_code"]
