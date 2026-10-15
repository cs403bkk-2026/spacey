"""What /pay logs: fixed outcomes only, never card data or database
diagnostics. The functions /pay calls are patched, so neither the database
nor the Purchase service is reached."""

import logging
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from psycopg import OperationalError

from purchase import booking
from shared.logger import logger

PAYABLE = ({"id": 7, "status": "pending"}, 200)
CURSOR = SimpleNamespace(connection=None)
# What payment.services.collect returns for each outcome (ADR 0004).
COLLECTED = {
    "invalid_card": {"status": "failed", "payment_id": None,
                     "error": "card_number must be 13-19 digits"},
    "failed": {"status": "failed", "payment_id": 1, "error": "payment failed"},
    "unknown": {"status": "unknown", "payment_id": 1, "error": None},
    "succeeded": {"status": "paid", "payment_id": 1, "error": None},
}


class PayLoggingTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.dict(os.environ, {"PURCHASE_URL": "http://purchase.test"})
        )
        self.enterContext(patch.object(booking, "check_payable", return_value=PAYABLE))
        # PUR-027's flag off: /pay runs here, as these tests were written for.
        self.enterContext(patch.object(booking.client, "pays", return_value=False))

    def test_outcomes_exclude_card_data(self):
        now = datetime.now(timezone.utc)
        row = dict(id=7, paid=False, start_time=now, end_time=now,
                   created_at=now, card_last4=None, amount_cents=2500)
        card = dict(card_number="4111111111111111", expiry="12/99", cvc="987")
        for outcome, status in (("not_found", 404), ("already_paid", 200),
                                ("invalid_card", 400), ("failed", 402),
                                ("unknown", 504), ("succeeded", 200)):
            with self.subTest(outcome=outcome):
                found = (None if outcome == "not_found" else
                         {**row, "paid": outcome == "already_paid"})
                paid = {**row, "paid": True, "card_last4": "1111"}
                body = {**card, "force_failure": outcome == "failed"}
                if outcome == "invalid_card":
                    body["card_number"] = "sensitive-invalid-card"
                with (
                    patch.object(booking, "get_booking", return_value=found),
                    patch.object(booking, "collect",
                                 return_value=COLLECTED.get(outcome)),
                    patch.object(booking, "mark_paid", return_value=paid),
                    self.assertLogs(logger, level="DEBUG") as logs,
                ):
                    _, actual_status = booking.mark_booking_paid(
                        CURSOR, 7, body["card_number"], body["expiry"],
                        body["cvc"], body["force_failure"])
                self.assertEqual(actual_status, status)
                self.assertEqual(len(logs.records), 2)
                self.assertEqual(logs.records[0].levelno, logging.DEBUG)
                self.assertEqual(logs.records[0].getMessage(),
                                 "payment booking_id=7 outcome=started")
                self.assertEqual(logs.records[1].levelno,
                                 logging.INFO if status == 200 else logging.WARNING)
                self.assertEqual(logs.records[1].getMessage(),
                                 f"payment booking_id=7 outcome={outcome}")
                for value in (*card.values(), "1111", "sensitive-invalid-card"):
                    self.assertNotIn(value, "\n".join(logs.output))

    def test_database_errors_do_not_log_diagnostics(self):
        card = dict(card_number="4111111111111111", expiry="12/99", cvc="987")
        unpaid = {"id": 7, "paid": False, "amount_cents": 2500}
        for operation in ("select", "update"):
            with self.subTest(operation=operation):
                error = OperationalError(f"SQL parameters: {card!r}")
                # The read error comes from get_booking, the write error from mark_paid.
                read = ({"side_effect": error} if operation == "select"
                        else {"return_value": unpaid})
                with (
                    patch.object(booking, "get_booking", **read),
                    patch.object(booking, "collect", return_value=COLLECTED["succeeded"]),
                    patch.object(booking, "mark_paid", side_effect=error),
                    self.assertLogs(logger, level="DEBUG") as logs,
                ):
                    payload, status = booking.mark_booking_paid(CURSOR, 7, **card)
                self.assertEqual((payload, status), ({"error": "payment unavailable"}, 500))
                self.assertEqual(logs.records[-1].levelno, logging.ERROR)
                self.assertEqual(logs.records[-1].getMessage(),
                                 "payment booking_id=7 outcome=database_error")
                self.assertIsNone(logs.records[-1].exc_info)
                for value in card.values():
                    self.assertNotIn(value, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
