"""PT-010: controlled service-level race test, without the Purchase service:
the Purchase functions /pay calls are patched. Payments runs for real on the
test database (one connection per request), since its unique index is what
stops a second charge (PT-009)."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from app import create_app
from payment import services as payment_services
from payment.repository import get_payments_for_booking
from purchase import booking as booking_module


@pytest.mark.parametrize("concurrent", [False, True],
                         ids=["sequential-repeat", "concurrent-repeat"])
def test_same_booking_is_charged_once(monkeypatch, concurrent):
    app = create_app(reset_on_start=True)  # an empty payments table
    now = datetime.now(timezone.utc)
    booking = {
        "id": 1,
        "paid": False,
        "card_last4": None,
        "amount_cents": 2500,
        "start_time": now,
        "end_time": now,
        "created_at": now,
    }
    lock = Lock()
    both_read = Barrier(2)
    one_finished = Event()
    writes = []
    charges = []

    def get_booking(db, booking_id):
        assert booking_id == 1
        with lock:
            snapshot = booking.copy()
        if concurrent:
            # Both requests must read before either can update.
            both_read.wait(timeout=5)
        return snapshot

    def mark_paid(db, booking_id, last4):
        with lock:
            writes.append((booking_id, last4))
            booking.update(paid=True, card_last4=last4)
            return booking.copy()

    def charge_card(*args):
        with lock:
            charges.append(args)
        if concurrent:
            # Hold the charge until the other request has finished, so it
            # meets this attempt while it is still in progress.
            assert one_finished.wait(timeout=5), "both requests are charging the card"
        return None  # the card is accepted

    monkeypatch.setenv("PURCHASE_URL", "http://purchase.test")
    monkeypatch.setattr(booking_module.client, "pays", lambda: False)  # PUR-027's flag off
    monkeypatch.setattr(booking_module, "get_booking", get_booking)
    monkeypatch.setattr(
        booking_module,
        "check_payable",
        lambda db, booking_id: ({"id": 1, "status": "pending"}, 200),
    )
    monkeypatch.setattr(booking_module, "mark_paid", mark_paid)
    monkeypatch.setattr(payment_services, "charge_card", charge_card)

    card = {
        "card_number": "4242424242424242",
        "expiry": f"12/{(now.year + 1) % 100:02d}",
        "cvc": "123",
    }

    def pay():
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                             autocommit=True) as conn:
            result = booking_module.mark_booking_paid(
                SimpleNamespace(connection=conn), 1,
                card["card_number"], card["expiry"], card["cvc"],
            )
        one_finished.set()
        return result

    if concurrent:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(pay) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
    else:
        results = [pay(), pay()]

    successes = [p for p in get_payments_for_booking(app.db, 1)
                 if p["status"] == "success"]
    assert len(charges) == 1, f"the card was charged {len(charges)} times"
    assert len(successes) == 1
    assert booking["paid"] is True
    assert len(writes) == 1, f"mark_paid was called {len(writes)} times"
    if concurrent:
        # The request that met the attempt in progress is told so, not failed.
        assert sorted(status for _, status in results) == [200, 504]
        assert ({"error": "payment outcome unknown"}, 504) in results
    else:
        assert all(status == 200 for _, status in results)
        assert results[0] == results[1]
