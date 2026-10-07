import logging
import os
import subprocess
import sys
import unittest
from flask import Flask

from payment.api import payment_bp
from payment.services import logger, pay_booking, process_payment


class PaymentLoggingTest(unittest.TestCase):
    def test_logging_works_without_app_configuration(self):
        code = (
            "from payment.services import logger; "
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
        card = dict(card_number="4111111111111111", expiry="12/99", cvc="987")
        for entry in ("json", "direct"):
            for outcome, status in (("invalid_card", 400), ("failed", 402),
                                    ("succeeded", 200)):
                with self.subTest(entry=entry, outcome=outcome):
                    body = {**card, "force_failure": outcome == "failed"}
                    if outcome == "invalid_card":
                        body["card_number"] = "sensitive-invalid-card"
                    with self.assertLogs(logger, level="DEBUG") as logs:
                        if entry == "json":
                            payload, actual_status = pay_booking(7, body)
                        else:
                            payload, actual_status = process_payment(
                                7, body["card_number"], body["expiry"],
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
                    for value in (*card.values(), "sensitive-invalid-card"):
                        self.assertNotIn(value, str(payload))
                    if status == 200:
                        self.assertEqual(payload, {
                            "booking_id": 7, "status": "success", "card_last4": "1111"})
                    else:
                        self.assertEqual(set(payload), {"error"})


class PaymentApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(payment_bp)
        self.client = app.test_client()  # No database configured.
        self.card = dict(card_number="4111111111111111", expiry="12/99", cvc="987")

    def test_success_returns_only_payment_outcome(self):
        response = self.client.post("/bookings/7/pay", json=self.card)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "booking_id": 7, "status": "success", "card_last4": "1111"})

    def test_invalid_cards_return_existing_errors(self):
        cases = [
            ({}, "card_number must be 13-19 digits"),
            ({"card_number": "bad"}, "card_number must be 13-19 digits"),
            ({"card_number": "4111111111111112"}, "card_number is not a valid card number"),
            ({"expiry": None}, "expiry must be in MM/YY format"),
            ({"expiry": "13/99"}, "expiry must be in MM/YY format"),
            ({"expiry": "01/00"}, "card has expired"),
            ({"cvc": None}, "cvc must be 3 or 4 digits"),
            ({"cvc": "bad"}, "cvc must be 3 or 4 digits"),
        ]
        for fields, error in cases:
            with self.subTest(fields=fields):
                body = {**self.card, **fields} if fields else {}
                response = self.client.post("/bookings/7/pay", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": error})

    def test_non_object_and_malformed_json_are_rejected(self):
        for body in ('null', '[]', '"card"', '42', 'true', '{'):
            with self.subTest(body=body):
                response = self.client.post(
                    "/bookings/7/pay", data=body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {
                    "error": "card_number must be 13-19 digits"})

    def test_forced_failure_returns_existing_error(self):
        response = self.client.post(
            "/bookings/7/pay", json={**self.card, "force_failure": True})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.get_json(), {"error": "payment failed"})

    def test_confirmation_route_is_removed(self):
        response = self.client.post("/bookings/7/confirmation/pay", data=self.card)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
