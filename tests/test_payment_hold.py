from datetime import datetime, timedelta, timezone

from app import create_app
from purchase import expire_unpaid_bookings


CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}


def test_failed_payment_hold_retry_expiry_and_paid_protection():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    now = datetime.now(timezone.utc)
    slot = {
        "member": "hold-test",
        "start_time": (now + timedelta(hours=1)).isoformat(),
        "end_time": (now + timedelta(hours=2)).isoformat(),
    }
    booking = client.post("/spaces/1/bookings", json=slot).get_json()
    bid = booking["id"]
    assert client.post(f"/bookings/{bid}/pay", json={**CARD, "force_failure": True}).status_code == 402
    assert client.get(f"/bookings/{bid}").get_json() == booking
    assert client.post("/spaces/1/bookings", json=slot).status_code == 409
    assert client.post(f"/bookings/{bid}/unlock").status_code == 402
    assert client.get("/metrics").get_json()["revenue_cents"] == 0

    # Just before the deadline, a retry succeeds without replacing the booking.
    with app.db.cursor() as cur:
        cur.execute("UPDATE bookings SET created_at = now() - INTERVAL '14 minutes' WHERE id = %s", (bid,))
    paid = client.post(f"/bookings/{bid}/pay", json=CARD).get_json()
    assert paid["id"] == bid and paid["paid"] is True
    assert paid["amount_cents"] == booking["amount_cents"]
    with app.db.cursor() as cur:
        cur.execute("UPDATE bookings SET created_at = now() - INTERVAL '16 minutes' WHERE id = %s", (bid,))
    assert client.post(f"/bookings/{bid}/pay", json={}).status_code == 200
    assert client.post(f"/bookings/{bid}/unlock").status_code == 200
    assert client.get("/metrics").get_json()["revenue_cents"] == booking["amount_cents"]

    client.delete(f"/bookings/{bid}")
    expired = client.post("/spaces/1/bookings", json=slot).get_json()["id"]
    # Use database time to put the hold at the inclusive 15-minute cutoff.
    with app.db.transaction():
        with app.db.cursor() as cur:
            cur.execute("UPDATE bookings SET created_at = statement_timestamp() - INTERVAL '15 minutes' WHERE id = %s", (expired,))
            expire_unpaid_bookings(cur)
            cur.execute("SELECT id FROM bookings WHERE id = %s", (expired,))
            assert cur.fetchone() is None
    assert client.post(f"/bookings/{expired}/pay", json=CARD).status_code == 404
    assert client.post(f"/bookings/{expired}/unlock").status_code == 404
    assert client.get("/spaces/1", query_string={k: v for k, v in slot.items() if k != "member"}).get_json()["available"] is True
    assert client.post("/spaces/1/bookings", json=slot).status_code == 201


def test_request_releases_expired_hold_before_checking_overlap():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    now = datetime.now(timezone.utc)
    slot = {"member": "hold-test", "start_time": now.isoformat(), "end_time": (now + timedelta(hours=1)).isoformat()}
    booking = client.post("/spaces/1/bookings", json=slot).get_json()
    with app.db.cursor() as cur:
        cur.execute("UPDATE bookings SET created_at = now() - INTERVAL '15 minutes' WHERE id = %s", (booking["id"],))
    assert client.post("/spaces/1/bookings", json=slot).status_code == 201
    assert client.get(f"/bookings/{booking['id']}").status_code == 404


def test_payment_cannot_cross_the_hold_deadline(monkeypatch):
    import payment.services as payment_services

    app = create_app(reset_on_start=True)
    client = app.test_client()
    now = datetime.now(timezone.utc)
    booking = client.post("/spaces/1/bookings", json={
        "member": "hold-test", "start_time": now.isoformat(),
        "end_time": (now + timedelta(hours=1)).isoformat(),
    }).get_json()

    def validation_crosses_deadline(*args):
        with app.db.cursor() as cur:
            cur.execute("UPDATE bookings SET created_at = now() - INTERVAL '15 minutes' WHERE id = %s", (booking["id"],))
        return None

    monkeypatch.setattr(payment_services, "validate_card", validation_crosses_deadline)
    assert client.post(f"/bookings/{booking['id']}/pay", json=CARD).status_code == 404
    assert client.get("/metrics").get_json()["revenue_cents"] == 0
