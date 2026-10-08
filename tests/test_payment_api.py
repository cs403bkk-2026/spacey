import unittest
from flask import Flask

from payment.api import payment_bp
from purchase.api import booking_bp


class PaymentApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(payment_bp)
        self.client = app.test_client()  # No database configured.
        self.card = dict(card_number="4111111111111111", expiry="12/99", cvc="987")

    def test_success_returns_only_payment_outcome(self):
        response = self.client.post("/payment/bookings/7/pay", json=self.card)
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
                response = self.client.post("/payment/bookings/7/pay", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": error})

    def test_non_object_and_malformed_json_are_rejected(self):
        for body in ('null', '[]', '"card"', '42', 'true', '{'):
            with self.subTest(body=body):
                response = self.client.post(
                    "/payment/bookings/7/pay", data=body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {
                    "error": "card_number must be 13-19 digits"})

    def test_forced_failure_returns_existing_error(self):
        response = self.client.post(
            "/payment/bookings/7/pay", json={**self.card, "force_failure": True})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.get_json(), {"error": "payment failed"})

    def test_confirmation_route_is_removed(self):
        response = self.client.post("/bookings/7/confirmation/pay", data=self.card)
        self.assertEqual(response.status_code, 404)

    def test_payment_and_purchase_routes_do_not_conflict(self):
        self.client.application.register_blueprint(booking_bp)
        routes = self.client.application.url_map.bind("localhost")
        self.assertEqual(routes.match("/payment/bookings/7/pay", method="POST"),
                         ("payment.pay_booking", {"booking_id": 7}))
        self.assertEqual(routes.match("/bookings/7/pay", method="POST"),
                         ("booking.pay_booking", {"booking_id": 7}))


if __name__ == "__main__":
    unittest.main()
