from datetime import datetime, timedelta, timezone

import pytest

from app import create_app

NOW = datetime.now(timezone.utc)

def make_client():
    return create_app(reset_on_start=True).test_client()

def slot(start_hours, end_hours):
    """Booking times relative to now, e.g. slot(-1, 1) is happening right now."""
    return {
        "start_time": (NOW + timedelta(hours=start_hours)).isoformat(),
        "end_time": (NOW + timedelta(hours=end_hours)).isoformat(),
    }

# A mocked, obviously-fake card - always valid, never a real payment.
VALID_CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}

def test_pay_flips_a_booking_to_paid():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    assert created["paid"] is False

    response = client.post(f"/bookings/{created['id']}/pay", json=VALID_CARD)

    assert response.status_code == 200
    assert response.get_json() == {**created, "paid": True, "card_last4": "4242"}
    assert client.get(f"/bookings/{created['id']}").get_json()["paid"] is True

def test_paying_twice_is_still_paid():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{created['id']}/pay", json=VALID_CARD)

    response = client.post(f"/bookings/{created['id']}/pay", json=VALID_CARD)

    assert response.status_code == 200
    assert response.get_json()["paid"] is True

def test_pay_unknown_booking_returns_404():
    client = make_client()

    response = client.post("/bookings/999/pay", json=VALID_CARD)

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_paying_with_a_valid_card_succeeds_and_shows_only_last4():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    response = client.post(f"/bookings/{created['id']}/pay", json=VALID_CARD)

    assert response.status_code == 200
    body = response.get_json()
    assert body["paid"] is True
    assert body["card_last4"] == "4242"
    assert "card_number" not in body
    assert "cvc" not in body

def test_paying_with_a_missing_card_field_is_rejected_and_leaves_it_unpaid():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    for missing in ["card_number", "expiry", "cvc"]:
        card = {k: v for k, v in VALID_CARD.items() if k != missing}
        response = client.post(f"/bookings/{created['id']}/pay", json=card)

        assert response.status_code == 400
        assert "must" in response.get_json()["error"] or "format" in response.get_json()["error"]

    assert client.get(f"/bookings/{created['id']}").get_json()["paid"] is False

def test_paying_with_a_badly_formatted_card_is_rejected():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    cases = [
        ({**VALID_CARD, "card_number": "4242"}, "card_number"),
        ({**VALID_CARD, "card_number": "4242abcd42424242"}, "card_number"),
        ({**VALID_CARD, "cvc": "12"}, "cvc"),
        ({**VALID_CARD, "cvc": "abc"}, "cvc"),
        ({**VALID_CARD, "expiry": "13/30"}, "expiry"),
        ({**VALID_CARD, "expiry": "2030-12"}, "expiry"),
    ]
    for card, field in cases:
        response = client.post(f"/bookings/{created['id']}/pay", json=card)

        assert response.status_code == 400
        assert field in response.get_json()["error"]

    assert client.get(f"/bookings/{created['id']}").get_json()["paid"] is False

def test_paying_with_a_card_that_fails_the_luhn_check_is_rejected():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    # 4242424242424242 is valid; changing the last digit breaks the checksum
    response = client.post(
        f"/bookings/{created['id']}/pay",
        json={**VALID_CARD, "card_number": "4242424242424241"},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "card_number is not a valid card number"}
    assert client.get(f"/bookings/{created['id']}").get_json()["paid"] is False

# PT-005: boundary cases for card validation. Card numbers below pass the Luhn
# check where they are meant to be accepted, so only the rule under test decides.

def pay_with(client, booking_id, **overrides):
    return client.post(f"/bookings/{booking_id}/pay", json={**VALID_CARD, **overrides})

def new_unpaid_booking(client, n):
    """A separate one-hour slot per call, so cases don't clash or share state."""
    return client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(n * 2, n * 2 + 1)}
    ).get_json()["id"]

def expiry_months_from_now(months):
    """MM/YY for the given number of months from the current UTC month."""
    now = datetime.now(timezone.utc)
    index = now.year * 12 + (now.month - 1) + months
    return f"{index % 12 + 1:02d}/{(index // 12) % 100:02d}"

@pytest.mark.parametrize(
    "card_number, accepted",
    [
        ("424242424242", False),             # 12 digits, one too short
        ("4222222222222", True),             # 13 digits, shortest allowed
        ("6011000000000000001", True),       # 19 digits, longest allowed
        ("42424242424242424242", False),     # 20 digits, one too long
        ("4242 4242 4242 4242", False),      # spaces are not accepted
        ("4242-4242-4242-4242", False),      # dashes are not accepted
        ("", False),
        (4242424242424242, False),           # a number, not a string
        (None, False),
        (["4242424242424242"], False),
    ],
)
def test_card_number_length_and_type_boundaries(card_number, accepted):
    client = make_client()
    booking_id = new_unpaid_booking(client, 1)

    response = pay_with(client, booking_id, card_number=card_number)

    if accepted:
        assert response.status_code == 200
        assert response.get_json()["paid"] is True
    else:
        assert response.status_code == 400
        assert response.get_json() == {"error": "card_number must be 13-19 digits"}
        assert client.get(f"/bookings/{booking_id}").get_json()["paid"] is False

@pytest.mark.parametrize(
    "cvc, accepted",
    [
        ("12", False),      # 2 digits, too short
        ("123", True),      # 3 digits
        ("1234", True),     # 4 digits
        ("12345", False),   # 5 digits, too long
        ("", False),
        (" 123", False),    # whitespace
        (123, False),       # a number, not a string
        (None, False),
    ],
)
def test_cvc_length_and_type_boundaries(cvc, accepted):
    client = make_client()
    booking_id = new_unpaid_booking(client, 1)

    response = pay_with(client, booking_id, cvc=cvc)

    if accepted:
        assert response.status_code == 200
    else:
        assert response.status_code == 400
        assert response.get_json() == {"error": "cvc must be 3 or 4 digits"}
        assert client.get(f"/bookings/{booking_id}").get_json()["paid"] is False

@pytest.mark.parametrize(
    "months_from_now, accepted",
    [
        (-1, False),   # last month: expired
        (0, True),     # this month: still valid
        (1, True),     # next month
    ],
)
def test_expiry_month_boundary(months_from_now, accepted):
    client = make_client()
    booking_id = new_unpaid_booking(client, 1)

    response = pay_with(client, booking_id, expiry=expiry_months_from_now(months_from_now))

    if accepted:
        assert response.status_code == 200
    else:
        assert response.status_code == 400
        assert response.get_json() == {"error": "card has expired"}
        assert client.get(f"/bookings/{booking_id}").get_json()["paid"] is False

@pytest.mark.parametrize(
    "expiry",
    ["00/30", "13/30", "1/30", "12/2030", "12-30", "1230", "12/3", "", " 12/30", 1230, None],
)
def test_malformed_expiry_is_rejected_as_a_format_error(expiry):
    client = make_client()
    booking_id = new_unpaid_booking(client, 1)

    response = pay_with(client, booking_id, expiry=expiry)

    assert response.status_code == 400
    assert response.get_json() == {"error": "expiry must be in MM/YY format"}
    assert client.get(f"/bookings/{booking_id}").get_json()["paid"] is False

def test_the_first_failing_card_field_decides_the_error():
    client = make_client()
    booking_id = new_unpaid_booking(client, 1)

    # Everything is wrong at once: the card number is reported first, then cvc, then expiry.
    all_bad = {"card_number": "42", "cvc": "1", "expiry": "99/99"}
    assert pay_with(client, booking_id, **all_bad).get_json() == {
        "error": "card_number must be 13-19 digits"
    }
    assert pay_with(client, booking_id, **{**all_bad, "card_number": "4242424242424242"}).get_json() == {
        "error": "cvc must be 3 or 4 digits"
    }
    assert pay_with(client, booking_id, **{**all_bad, "card_number": "4242424242424242", "cvc": "123"}).get_json() == {
        "error": "expiry must be in MM/YY format"
    }
    assert client.get(f"/bookings/{booking_id}").get_json()["paid"] is False

def test_confirmation_page_pay_form_has_card_fields_and_shows_last4_once_paid():
    client = make_client()
    # Standard test numbers: Visa 16, Amex 15, a 13-digit and a 19-digit number
    for number in ["4111111111111111", "378282246310005", "4222222222222", "6011000000000000001"]:
        created = client.post(
            "/spaces/1/bookings", json={"member": "annabel", **slot(10 * len(number), 10 * len(number) + 1)}
        ).get_json()

        response = client.post(
            f"/bookings/{created['id']}/pay", json={**VALID_CARD, "card_number": number}
        )

        assert response.status_code == 200, number
        assert response.get_json()["card_last4"] == number[-4:]

def test_paying_with_an_expired_card_is_rejected():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    response = client.post(
        f"/bookings/{created['id']}/pay", json={**VALID_CARD, "expiry": "01/20"}
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "card has expired"}
    assert client.get(f"/bookings/{created['id']}").get_json()["paid"] is False

def test_paying_an_already_paid_booking_again_is_still_a_no_op():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{created['id']}/pay", json=VALID_CARD)

    # no card needed the second time - it's already paid
    response = client.post(f"/bookings/{created['id']}/pay", json={})

    assert response.status_code == 200
    assert response.get_json()["paid"] is True
    assert response.get_json()["card_last4"] == "4242"

def test_failed_payment_leaves_the_booking_unpaid_and_unlock_returns_402():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)}
    ).get_json()

    response = client.post(
        f"/bookings/{created['id']}/pay", json={**VALID_CARD, "force_failure": True}
    )

    assert response.status_code == 402
    assert response.get_json() == {"error": "payment failed"}
    assert client.get(f"/bookings/{created['id']}").get_json()["paid"] is False

    unlock = client.post(f"/bookings/{created['id']}/unlock")
    assert unlock.status_code == 402
    assert unlock.get_json() == {"error": "booking is not paid"}

def test_failed_payment_brings_in_no_revenue_and_can_be_retried():
    client = make_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )
    booking = client.post(
        "/spaces/2/bookings", json={"member": "gregory", **slot(1, 2)}
    ).get_json()

    client.post(f"/bookings/{booking['id']}/pay", json={**VALID_CARD, "force_failure": True})
    after_failure = client.get("/metrics").get_json()

    assert after_failure["revenue_cents"] == 0
    assert after_failure["unpaid_bookings"] == 1

    retry = client.post(
        f"/bookings/{booking['id']}/pay", json={**VALID_CARD, "force_failure": False}
    )
    after_retry = client.get("/metrics").get_json()

    assert retry.status_code == 200
    assert retry.get_json()["paid"] is True
    assert after_retry["revenue_cents"] == 1500
    assert after_retry["paid_bookings"] == 1

def test_forcing_a_failure_on_an_unknown_booking_returns_404():
    client = make_client()

    response = client.post("/bookings/999/pay", json={**VALID_CARD, "force_failure": True})

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_forcing_a_failure_on_a_paid_booking_leaves_it_paid():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{created['id']}/pay", json=VALID_CARD)

    response = client.post(
        f"/bookings/{created['id']}/pay", json={**VALID_CARD, "force_failure": True}
    )

    assert response.status_code == 200
    assert response.get_json()["paid"] is True

def test_paying_twice_only_counts_revenue_once():
    client = make_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )
    booking = client.post(
        "/spaces/2/bookings", json={"member": "gregory", **slot(1, 2)}
    ).get_json()

    first = client.post(f"/bookings/{booking['id']}/pay", json=VALID_CARD)
    second = client.post(f"/bookings/{booking['id']}/pay", json=VALID_CARD)
    metrics = client.get("/metrics").get_json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert metrics["revenue_cents"] == 1500
    assert metrics["paid_bookings"] == 1


def test_refund_payment_records_a_refund_in_payments():
    from payment.services import refund_payment
    from payment.repository import get_payments_for_booking
    app = create_app(reset_on_start=True)
    refund = refund_payment(
        app.db,
        booking_id=42,
        amount_cents=1500,
        card_last4="4242",
        reason="cancellation",
    )
    assert refund["status"] == "refunded"
    assert refund["amount_cents"] == 1500
    assert refund["card_last4"] == "4242"
    assert refund["booking_id"] == 42
    assert refund["reason"] == "cancellation"

    records = get_payments_for_booking(app.db, 42)
    assert len(records) == 1
    assert records[0]["status"] == "refunded"


def test_refund_payment_can_be_imported_from_service():
    from payment.service import refund_payment, refund_booking
    assert callable(refund_payment)
    assert callable(refund_booking)


def test_refund_booking_backward_compatibility():
    from payment.services import refund_booking
    app = create_app(reset_on_start=True)
    refund = refund_booking(
        app.db,
        booking_id=99,
        amount_cents=500,
    )
    assert refund["status"] == "refunded"
    assert refund["amount_cents"] == 500



# --- PT-009: every payment attempt is recorded; collect and payment_status (ADR 0004) ---

def attempts(app, booking_id):
    from payment.repository import get_payments_for_booking
    return get_payments_for_booking(app.db, booking_id)


def test_paying_records_one_successful_attempt_with_only_the_last4():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    booking_id = new_unpaid_booking(client, 1)
    booking = client.get(f"/bookings/{booking_id}").get_json()

    assert pay_with(client, booking_id).status_code == 200

    [payment] = attempts(app, booking_id)
    assert payment["status"] == "success"
    assert payment["amount_cents"] == booking["amount_cents"]
    assert payment["currency"] == "USD"
    assert payment["card_last4"] == "4242"
    assert payment["reason"] is None
    assert VALID_CARD["card_number"] not in str(payment)


def test_a_declined_attempt_is_recorded_and_a_retry_succeeds():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    booking_id = new_unpaid_booking(client, 1)

    assert pay_with(client, booking_id, force_failure=True).status_code == 402
    assert pay_with(client, booking_id).status_code == 200

    recorded = attempts(app, booking_id)
    assert [(p["status"], p["reason"]) for p in recorded] == [
        ("failed", "payment failed"), ("success", None)]


@pytest.mark.parametrize("repeat", ["already_paid", "invalid_card"])
def test_repeats_and_invalid_cards_record_no_attempt(repeat):
    app = create_app(reset_on_start=True)
    client = app.test_client()
    booking_id = new_unpaid_booking(client, 1)
    if repeat == "already_paid":
        pay_with(client, booking_id)
        expected = ["success"]
    else:
        expected = []

    pay_with(client, booking_id, cvc="1")

    assert [p["status"] for p in attempts(app, booking_id)] == expected


def test_collect_after_a_success_returns_the_same_payment_without_charging(monkeypatch):
    from payment import services
    app = create_app(reset_on_start=True)
    first = services.collect(app.db, 7, 2500, **VALID_CARD)
    charges = []
    monkeypatch.setattr(services, "charge_card", lambda *args: charges.append(args))

    again = services.collect(app.db, 7, 2500, **VALID_CARD)

    assert first == {"status": "paid", "payment_id": first["payment_id"], "error": None}
    assert again == first
    assert charges == []
    assert len(attempts(app, 7)) == 1


def test_collect_reports_invalid_cards_and_declines_as_failed():
    from payment import services
    app = create_app(reset_on_start=True)

    invalid = services.collect(app.db, 7, 2500, **{**VALID_CARD, "cvc": "1"})
    declined = services.collect(app.db, 7, 2500, **VALID_CARD, force_failure=True)

    assert invalid == {"status": "failed", "payment_id": None,
                       "error": "cvc must be 3 or 4 digits"}
    assert declined == {"status": "failed", "payment_id": declined["payment_id"],
                        "error": "payment failed"}
    assert [p["id"] for p in attempts(app, 7)] == [declined["payment_id"]]


def test_collect_for_a_free_booking_stores_nothing():
    from payment import services
    app = create_app(reset_on_start=True)

    result = services.collect(app.db, 7, 0, **VALID_CARD)

    assert result == {"status": "paid", "payment_id": None, "error": None}
    assert attempts(app, 7) == []


def test_an_unknown_outcome_is_not_a_failure_and_is_never_charged_twice(monkeypatch):
    from payment import services
    app = create_app(reset_on_start=True)
    client = app.test_client()
    booking_id = new_unpaid_booking(client, 1)
    charges = []

    def lost_answer(*args):
        charges.append(args)
        raise services.ProviderUnavailable

    monkeypatch.setattr(services, "charge_card", lost_answer)

    first = pay_with(client, booking_id)
    again = pay_with(client, booking_id)

    for response in (first, again):
        assert response.status_code == 504
        assert response.get_json() == {"error": "payment outcome unknown"}
    assert len(charges) == 1
    assert client.get(f"/bookings/{booking_id}").get_json()["paid"] is False
    assert client.post(f"/bookings/{booking_id}/unlock").status_code == 402
    [payment] = attempts(app, booking_id)
    assert payment["status"] == "unknown"
    assert services.payment_status(app.db, booking_id) == {
        "status": "unknown", "payment_id": payment["id"]}


def test_payment_status_reports_none_failed_then_paid():
    from payment import services
    app = create_app(reset_on_start=True)

    before = services.payment_status(app.db, 7)
    declined = services.collect(app.db, 7, 2500, **VALID_CARD, force_failure=True)
    after_decline = services.payment_status(app.db, 7)
    paid = services.collect(app.db, 7, 2500, **VALID_CARD)
    after_payment = services.payment_status(app.db, 7)

    assert before == {"status": "none", "payment_id": None}
    assert after_decline == {"status": "failed", "payment_id": declined["payment_id"]}
    assert after_payment == {"status": "paid", "payment_id": paid["payment_id"]}


def test_the_database_allows_one_open_or_successful_attempt_per_booking():
    import psycopg
    from payment.repository import insert_payment
    app = create_app(reset_on_start=True)
    insert_payment(app.db, 7, 2500, "failed")
    insert_payment(app.db, 7, 2500, "failed")  # retries after a decline are fine
    insert_payment(app.db, 7, 2500, "success")
    insert_payment(app.db, 7, 2500, "refunded")

    for status in ("success", "unknown"):
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_payment(app.db, 7, 2500, status)
    insert_payment(app.db, 8, 2500, "success")  # another booking is unaffected


def test_the_index_migration_runs_on_existing_payments():
    from payment.migrations import run_migrations
    from payment.repository import insert_payment
    app = create_app(reset_on_start=True)
    with app.db.cursor() as cur:
        cur.execute("DROP INDEX payments_one_open_or_paid_per_booking")
    # What production can hold today: refunds and at most one success each.
    insert_payment(app.db, 7, 2500, "success")
    insert_payment(app.db, 7, 2500, "refunded")
    insert_payment(app.db, 8, 1000, "refunded")

    run_migrations(app.db)
    run_migrations(app.db)

    assert len(attempts(app, 7)) == 2
