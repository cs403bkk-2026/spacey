"""PT-010: controlled service-level race test, without a real database."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock

import pytest

from purchase import booking as booking_module


@pytest.mark.parametrize(
    "concurrent",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="PT-010: concurrent unpaid reads reach mark_paid twice",
            ),
        ),
    ],
    ids=["sequential-repeat", "concurrent-repeat"],
)
def test_same_booking_reaches_mark_paid_once(monkeypatch, concurrent):
    now = datetime.now(timezone.utc)
    booking = {
        "id": 1,
        "paid": False,
        "card_last4": None,
        "start_time": now,
        "end_time": now,
        "created_at": now,
    }
    lock = Lock()
    both_read = Barrier(2)
    writes = []

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

    monkeypatch.setattr(booking_module, "get_booking", get_booking)
    monkeypatch.setattr(booking_module, "mark_paid", mark_paid)

    card = {
        "card_number": "4242424242424242",
        "expiry": f"12/{(now.year + 1) % 100:02d}",
        "cvc": "123",
    }

    def pay():
        return booking_module.mark_booking_paid(
            None, 1, card["card_number"], card["expiry"], card["cvc"]
        )

    if concurrent:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(pay) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
    else:
        results = [pay(), pay()]

    assert all(status == 200 for _, status in results)
    assert results[0] == results[1]
    assert booking["paid"] is True
    assert len(writes) == 1, f"mark_paid was called {len(writes)} times"
