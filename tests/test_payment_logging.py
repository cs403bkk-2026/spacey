import logging
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from psycopg import OperationalError

from log import logger
from purchase.booking import mark_booking_paid


class PaymentLoggingTest(unittest.TestCase):
    def test_logging_works_without_app_configuration(self):
        code = (
            "from log import logger; "
            "logger.debug('payment booking_id=7 outcome=started'); "
            "logger.info('payment booking_id=7 outcome=succeeded')"
        )
        for level in (None, "DEBUG"):
            with self.subTest(level=level):
                env = dict(os.environ)
                env.pop("LOG_LEVEL", None)
                if level:
                    env["LOG_LEVEL"] = level
                result = subprocess.run(
                    [sys.executable, "-c", code], env=env,
                    capture_output=True, text=True, check=True)
                expected = "INFO payment booking_id=7 outcome=succeeded\n"
                if level == "DEBUG":
                    expected = "DEBUG payment booking_id=7 outcome=started\n" + expected
                self.assertEqual(result.stderr, expected)

    def test_outcomes_exclude_card_data(self):
        now = datetime.now(timezone.utc)
        row = dict(id=7, paid=False, start_time=now, end_time=now,
                   created_at=now, card_last4=None)
        card = dict(card_number="4111111111111111", expiry="12/99", cvc="987")
        for outcome, status in (("not_found", 404), ("already_paid", 200),
                                ("invalid_card", 400), ("failed", 402),
                                ("succeeded", 200)):
            with self.subTest(outcome=outcome):
                cur = MagicMock()
                cur.fetchone.side_effect = [
                    None if outcome == "not_found" else
                    {**row, "paid": outcome == "already_paid"},
                    {**row, "paid": True, "card_last4": "1111"},
                ]
                body = {**card, "force_failure": outcome == "failed"}
                if outcome == "invalid_card":
                    body["card_number"] = "sensitive-invalid-card"
                with self.assertLogs(logger, level="DEBUG") as logs:
                    _, actual_status = mark_booking_paid(
                        cur, 7, body["card_number"], body["expiry"],
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
        for operation in ("select", "update"):
            with self.subTest(operation=operation):
                error = OperationalError(f"SQL parameters: {card!r}")
                cur = MagicMock()
                cur.fetchone.return_value = {"paid": False}
                cur.execute.side_effect = [error] if operation == "select" else [None, error]
                with self.assertLogs(logger, level="DEBUG") as logs:
                    payload, status = mark_booking_paid(cur, 7, **card)
                self.assertEqual((payload, status), ({"error": "payment unavailable"}, 500))
                self.assertEqual(logs.records[-1].levelno, logging.ERROR)
                self.assertEqual(logs.records[-1].getMessage(),
                                 "payment booking_id=7 outcome=database_error")
                self.assertIsNone(logs.records[-1].exc_info)
                for value in card.values():
                    self.assertNotIn(value, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
