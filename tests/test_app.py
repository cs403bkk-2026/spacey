import threading
from datetime import datetime, timedelta, timezone

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

def test_homepage_lists_spaces_with_availability():
    client = make_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )
    client.post("/spaces/2/bookings", json={"member": "gregory", **slot(-1, 1)})

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Founders Desk" in body
    assert "available" in body
    assert "Meeting Room A" in body
    assert "$15.00" in body
    assert "booked" in body

BANGKOK = timezone(timedelta(hours=7))

def form_slot(start_hours, end_hours):
    """What the browser's datetime-local fields send: a local (Bangkok)
    wall-clock time with no timezone on it."""
    local_now = NOW.astimezone(BANGKOK)
    return {
        "start_time": (local_now + timedelta(hours=start_hours)).strftime(
            "%Y-%m-%dT%H:%M"
        ),
        "end_time": (local_now + timedelta(hours=end_hours)).strftime(
            "%Y-%m-%dT%H:%M"
        ),
    }

def test_homepage_shows_a_booking_form_only_for_available_spaces():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6})
    client.post("/spaces/2/bookings", json={"member": "gregory", **slot(-1, 1)})

    body = client.get("/").get_data(as_text=True)

    assert '<form method="post" action="/spaces/1/book">' in body
    assert 'name="member"' in body
    assert body.count("<form") == 1  # space 2 is booked right now, so no form

def test_booking_through_the_form_makes_the_space_unavailable():
    client = make_client()

    response = client.post(
        "/spaces/1/book", data={"member": "annabel", **form_slot(-1, 1)}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/bookings/1/confirmation"

    body = client.get("/").get_data(as_text=True)
    assert "booked" in body
    assert "<form" not in body  # the only space is taken now

    booking = client.get("/bookings/1").get_json()
    assert booking["member"] == "annabel"
    assert booking["paid"] is False

def test_book_pay_unlock_all_the_way_through_the_browser():
    client = make_client()

    booked = client.post(
        "/spaces/1/book", data={"member": "annabel", **form_slot(-1, 1)}
    )
    page = client.get(booked.headers["Location"]).get_data(as_text=True)

    # the confirmation page shows the booking, and asks for payment first
    assert "Booking #1" in page
    assert "Founders Desk" in page
    assert "annabel" in page
    assert "Not paid yet" in page
    assert ">Pay</button>" in page
    assert ">Unlock</button>" not in page

    paid = client.post("/bookings/1/confirmation/pay")
    page = client.get(paid.headers["Location"]).get_data(as_text=True)

    assert "Paid." in page
    assert ">Unlock</button>" in page

    unlocked = client.post("/bookings/1/confirmation/unlock")
    page = client.get(unlocked.headers["Location"]).get_data(as_text=True)

    assert "Your access code:" in page
    code = page.split("<strong>")[1].split("</strong>")[0]
    assert len(code) == 8  # secrets.token_hex(4)

def test_confirmation_page_unlock_without_paying_shows_the_error():
    client = make_client()
    client.post("/spaces/1/book", data={"member": "annabel", **form_slot(1, 2)})

    response = client.post("/bookings/1/confirmation/unlock")
    page = client.get(response.headers["Location"]).get_data(as_text=True)

    assert "booking is not paid" in page
    assert "Your access code" not in page

def test_confirmation_page_for_unknown_booking_returns_404():
    client = make_client()

    response = client.get("/bookings/999/confirmation")

    assert response.status_code == 404
    assert "Booking not found" in response.get_data(as_text=True)

def test_confirmation_page_shows_times_in_bangkok_time():
    client = make_client()
    client.post(
        "/spaces/1/book",
        data={
            "member": "annabel",
            "start_time": "2026-09-25T09:00",
            "end_time": "2026-09-25T10:00",
        },
    )

    page = client.get("/bookings/1/confirmation").get_data(as_text=True)

    assert "2026-09-25 09:00" in page
    assert "2026-09-25 10:00" in page

def test_confirmation_page_shows_the_total_before_and_after_paying():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500})

    client.post("/spaces/2/book", data={"member": "annabel", **form_slot(1, 2)})
    before = client.get("/bookings/1/confirmation").get_data(as_text=True)
    assert "Not paid yet - total $15.00" in before
    assert ">Pay</button>" in before

    client.post("/bookings/1/confirmation/pay")
    after = client.get("/bookings/1/confirmation").get_data(as_text=True)
    assert "Paid. Total: $15.00" in after

def test_booking_responses_include_the_amount_charged():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500})

    created = client.post(
        "/spaces/2/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    assert created["amount_cents"] == 1500

    # every other place a booking shows up agrees with what was charged
    assert client.get(f"/bookings/{created['id']}").get_json()["amount_cents"] == 1500
    assert client.get("/bookings").get_json()["bookings"][0]["amount_cents"] == 1500
    assert client.get("/spaces/2/bookings").get_json()["bookings"][0]["amount_cents"] == 1500
    paid = client.post(f"/bookings/{created['id']}/pay").get_json()
    assert paid["amount_cents"] == 1500
    cancelled = client.delete(f"/bookings/{created['id']}").get_json()
    assert cancelled["amount_cents"] == 1500

def test_a_price_change_after_booking_does_not_change_the_amount_shown():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6, "price_cents": 500})
    created = client.post(
        "/spaces/2/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    client.patch("/spaces/2", json={"price_cents": 2000})

    assert client.get(f"/bookings/{created['id']}").get_json()["amount_cents"] == 500

def test_a_subscribers_booking_shows_zero_amount_on_the_confirmation_page():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500})
    client.post("/members/annabel/subscribe")

    client.post("/spaces/2/book", data={"member": "annabel", **form_slot(1, 2)})
    page = client.get("/bookings/1/confirmation").get_data(as_text=True)

    assert "Paid. Total: $0.00" in page

def test_form_times_are_read_as_bangkok_time():
    client = make_client()

    client.post(
        "/spaces/1/book",
        data={
            "member": "annabel",
            "start_time": "2026-09-25T09:00",
            "end_time": "2026-09-25T10:00",
        },
    )

    booking = client.get("/bookings/1").get_json()
    # 09:00 in Bangkok (UTC+7) is 02:00 UTC
    assert booking["start_time"] == "2026-09-25T02:00:00+00:00"
    assert booking["end_time"] == "2026-09-25T03:00:00+00:00"

def test_form_booking_a_taken_slot_shows_the_error():
    client = make_client()
    client.post("/spaces/1/book", data={"member": "annabel", **form_slot(1, 3)})

    response = client.post(
        "/spaces/1/book", data={"member": "gregory", **form_slot(2, 4)}
    )

    assert response.status_code == 302
    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "space is already booked for that time" in body

def test_form_without_times_shows_an_error():
    client = make_client()

    response = client.post("/spaces/1/book", data={"member": "annabel"})

    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "fill in a start and end time" in body

def test_homepage_escapes_space_names():
    client = make_client()
    client.post(
        "/spaces", json={"name": "<script>alert(1)</script>", "capacity": 1}
    )

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body

def test_health_reports_running_revision(monkeypatch):
    monkeypatch.setenv("APP_REVISION", "test-revision")
    client = make_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "revision": "test-revision",
        "status": "ok",
    }

def test_list_spaces_returns_the_seed_space():
    client = make_client()

    response = client.get("/spaces")

    assert response.status_code == 200
    assert response.get_json() == {
        "spaces": [
            {
                "id": 1, 
                "name": "Founders Desk",
                "capacity": 1,
                "price_cents": 0,
                "available": True
             }
        ]
    }

def test_create_space_adds_a_new_space():
    client = make_client()

    response = client.post(
        "/spaces", json={"name": "Meeting Room A", "capacity": 6}
    )

    assert response.status_code == 201
    assert response.get_json() == {
        "id": 2,
        "name": "Meeting Room A",
        "capacity": 6,
        "price_cents": 0,
    }

    listed = client.get("/spaces").get_json()["spaces"]
    assert {
        "id": 2,
        "name": "Meeting Room A",
        "capacity": 6,
        "price_cents": 0,
        "available": True,
    } in listed

def test_create_space_with_a_price_stores_it():
    client = make_client()

    response = client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )

    assert response.status_code == 201
    assert response.get_json() == {
        "id": 2,
        "name": "Meeting Room A",
        "capacity": 6,
        "price_cents": 1500,
    }

def test_create_space_with_negative_price_is_rejected():
    client = make_client()

    response = client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": -100},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "price_cents must be a non-negative integer"
    }

def test_create_space_with_a_boolean_price_is_rejected():
    client = make_client()

    for price in [True, False]:
        response = client.post(
            "/spaces",
            json={"name": "Meeting Room A", "capacity": 6, "price_cents": price},
        )

        assert response.status_code == 400
        assert response.get_json() == {
            "error": "price_cents must be a non-negative integer"
        }

def test_create_space_without_capacity_is_rejected():
    client = make_client()

    response = client.post("/spaces", json={"name": "No Capacity Room"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "name and capacity are required"}

def test_create_space_with_empty_name_is_rejected():
    client = make_client()

    for name in ["", "   ", 42]:
        response = client.post("/spaces", json={"name": name, "capacity": 6})

        assert response.status_code == 400
        assert response.get_json() == {"error": "name must not be empty"}

def test_create_space_with_invalid_capacity_is_rejected():
    client = make_client()

    for capacity in [0, -5, "6", 2.5, True]:
        response = client.post(
            "/spaces", json={"name": "Meeting Room A", "capacity": capacity}
        )

        assert response.status_code == 400
        assert response.get_json() == {
            "error": "capacity must be a whole number of at least 1"
        }

    # nothing got created - only the seed space is there
    assert len(client.get("/spaces").get_json()["spaces"]) == 1

def test_create_space_trims_spaces_around_the_name():
    client = make_client()

    response = client.post(
        "/spaces", json={"name": "  Meeting Room A  ", "capacity": 6}
    )

    assert response.status_code == 201
    assert response.get_json()["name"] == "Meeting Room A"

def test_create_booking_for_existing_space_succeeds():
    client = make_client()

    response = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    )

    assert response.status_code == 201
    assert response.get_json() == {
        "id": 1,
        "space_id": 1,
        "member": "annabel",
        "paid": False,  # unpaid until /pay is called
        "amount_cents": 0,  # Founders Desk has no price set
        "user_id": None,  # not logged in
        **slot(1, 2),
    }

def test_create_booking_for_unknown_space_returns_404():
    client = make_client()

    response = client.post(
        "/spaces/999/bookings", json={"member": "annabel", **slot(1, 2)}
    )

    #404 to reject booking a space that doesn't exist
    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}

def test_create_booking_without_times_is_rejected():
    client = make_client()

    response = client.post("/spaces/1/bookings", json={"member": "annabel"})

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "start_time and end_time are required (ISO 8601 with timezone)"
    }

def test_create_booking_ending_before_it_starts_is_rejected():
    client = make_client()

    response = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(2, 1)}
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "end_time must be after start_time"}

def test_overlapping_booking_is_rejected():
    client = make_client()

    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(1, 3)})
    response = client.post(
        "/spaces/1/bookings", json={"member": "gregory", **slot(2, 4)}
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "space is already booked for that time"}

def test_concurrent_bookings_for_the_same_slot_only_one_succeeds():
    # Two separate app instances = two separate real DB connections, like
    # two simultaneous requests would get in production. This is what
    # actually exercises the race (see issue #50) rather than just the
    # single-connection check-then-insert code path.
    client_a = make_client()
    client_b = create_app(reset_on_start=False).test_client()

    booking = {"member": "racer", **slot(1, 2)}
    results = [None, None]
    start_barrier = threading.Barrier(2)

    def book(client, index):
        start_barrier.wait()
        results[index] = client.post("/spaces/1/bookings", json=booking)

    threads = [
        threading.Thread(target=book, args=(client_a, 0)),
        threading.Thread(target=book, args=(client_b, 1)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 409]

def test_back_to_back_bookings_are_allowed():
    client = make_client()

    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)})
    response = client.post(
        "/spaces/1/bookings", json={"member": "gregory", **slot(2, 3)}
    )

    assert response.status_code == 201

def test_space_booked_right_now_shows_as_unavailable():
    client = make_client()

    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)})
    response = client.get("/spaces")

    spaces = response.get_json()["spaces"]
    founders_desk = next(s for s in spaces if s["id"] == 1)
    assert founders_desk["available"] is False

def test_space_booked_only_later_is_still_available_now():
    client = make_client()

    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(24, 25)})
    response = client.get("/spaces")

    spaces = response.get_json()["spaces"]
    founders_desk = next(s for s in spaces if s["id"] == 1)
    assert founders_desk["available"] is True

def test_find_booking_returns_the_booking():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    response = client.get(f"/bookings/{created['id']}")

    assert response.status_code == 200
    assert response.get_json() == {
        "id": 1,
        "space_id": 1,
        "member": "annabel",
        "paid": False,
        "amount_cents": 0,
        "user_id": None,
        **slot(1, 2),
    }

def test_find_unknown_booking_returns_404():
    client = make_client()

    response = client.get("/bookings/999")

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_cancel_booking_makes_space_available_again():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)}
    ).get_json()

    response = client.delete(f"/bookings/{created['id']}")

    assert response.status_code == 200
    assert response.get_json() == created

    spaces = client.get("/spaces").get_json()["spaces"]
    founders_desk = next(s for s in spaces if s["id"] == 1)
    assert founders_desk["available"] is True

    assert client.get(f"/bookings/{created['id']}").status_code == 404

def test_cancel_unknown_booking_returns_404():
    client = make_client()

    response = client.delete("/bookings/999")

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_pay_flips_a_booking_to_paid():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    assert created["paid"] is False

    response = client.post(f"/bookings/{created['id']}/pay")

    assert response.status_code == 200
    assert response.get_json() == {**created, "paid": True}
    assert client.get(f"/bookings/{created['id']}").get_json()["paid"] is True

def test_paying_twice_is_still_paid():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{created['id']}/pay")

    response = client.post(f"/bookings/{created['id']}/pay")

    assert response.status_code == 200
    assert response.get_json()["paid"] is True

def test_pay_unknown_booking_returns_404():
    client = make_client()

    response = client.post("/bookings/999/pay")

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_failed_payment_leaves_the_booking_unpaid_and_unlock_returns_402():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)}
    ).get_json()

    response = client.post(
        f"/bookings/{created['id']}/pay", json={"force_failure": True}
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

    client.post(f"/bookings/{booking['id']}/pay", json={"force_failure": True})
    after_failure = client.get("/metrics").get_json()

    assert after_failure["revenue_cents"] == 0
    assert after_failure["unpaid_bookings"] == 1

    retry = client.post(
        f"/bookings/{booking['id']}/pay", json={"force_failure": False}
    )
    after_retry = client.get("/metrics").get_json()

    assert retry.status_code == 200
    assert retry.get_json()["paid"] is True
    assert after_retry["revenue_cents"] == 1500
    assert after_retry["paid_bookings"] == 1

def test_forcing_a_failure_on_an_unknown_booking_returns_404():
    client = make_client()

    response = client.post("/bookings/999/pay", json={"force_failure": True})

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_forcing_a_failure_on_a_paid_booking_leaves_it_paid():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{created['id']}/pay")

    response = client.post(
        f"/bookings/{created['id']}/pay", json={"force_failure": True}
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

    first = client.post(f"/bookings/{booking['id']}/pay")
    second = client.post(f"/bookings/{booking['id']}/pay")
    metrics = client.get("/metrics").get_json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert metrics["revenue_cents"] == 1500
    assert metrics["paid_bookings"] == 1

def test_unlock_before_paying_is_rejected():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)}
    ).get_json()

    response = client.post(f"/bookings/{created['id']}/unlock")

    assert response.status_code == 402
    assert response.get_json() == {"error": "booking is not paid"}

def test_unlock_a_paid_booking_returns_an_access_code():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)}
    ).get_json()
    client.post(f"/bookings/{created['id']}/pay")

    response = client.post(f"/bookings/{created['id']}/unlock")

    assert response.status_code == 200
    body = response.get_json()
    assert body["booking_id"] == created["id"]
    assert len(body["access_code"]) > 0

def test_unlock_unknown_booking_returns_404():
    client = make_client()

    response = client.post("/bookings/999/unlock")

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_registering_creates_an_account():
    client = make_client()

    response = client.post(
        "/register", json={"email": "Annabel@Example.com", "password": "hunter22"}
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body == {"id": 1, "email": "annabel@example.com"}
    assert "password" not in body
    assert "password_hash" not in body

def test_registering_does_not_store_the_plain_password():
    client = make_client()
    app = create_app(reset_on_start=False)
    client.post("/register", json={"email": "annabel@example.com", "password": "hunter22"})

    with app.db.cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE email = 'annabel@example.com'")
        stored = cur.fetchone()["password_hash"]

    assert stored != "hunter22"
    assert "hunter22" not in stored

def test_registering_with_a_duplicate_email_is_rejected():
    client = make_client()
    client.post("/register", json={"email": "annabel@example.com", "password": "hunter22"})

    # case shouldn't matter either
    response = client.post(
        "/register", json={"email": "Annabel@Example.com", "password": "different"}
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "email is already registered"}

def test_registering_with_a_bad_email_is_rejected():
    client = make_client()

    for email in ["not-an-email", "missing-domain@", "@missing-local.com", "", None, 42]:
        response = client.post(
            "/register", json={"email": email, "password": "hunter22"}
        )

        assert response.status_code == 400
        assert response.get_json() == {"error": "enter a valid email address"}

def test_registering_with_a_short_password_is_rejected():
    client = make_client()

    for password in ["short", "", None, 12345678]:
        response = client.post(
            "/register", json={"email": "annabel@example.com", "password": password}
        )

        assert response.status_code == 400
        assert response.get_json() == {
            "error": "password must be at least 8 characters"
        }

    # nothing got created
    assert client.get("/register").status_code == 200

def test_register_form_creates_an_account_and_redirects_with_a_message():
    client = make_client()

    response = client.post(
        "/register", data={"email": "annabel@example.com", "password": "hunter22"}
    )

    assert response.status_code == 302
    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Registered!" in body

def test_register_form_with_invalid_input_shows_the_error():
    client = make_client()

    response = client.post(
        "/register", data={"email": "not-an-email", "password": "hunter22"}
    )

    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "enter a valid email address" in body

def test_homepage_links_to_register():
    client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'href="/register"' in body

def register(client, email="annabel@example.com", password="hunter22"):
    return client.post("/register", json={"email": email, "password": password})

def test_login_with_the_right_password_succeeds():
    client = make_client()
    register(client)

    response = client.post(
        "/login", json={"email": "Annabel@Example.com", "password": "hunter22"}
    )

    assert response.status_code == 200
    assert response.get_json() == {"id": 1, "email": "annabel@example.com"}

def test_login_with_the_wrong_password_is_rejected():
    client = make_client()
    register(client)

    response = client.post(
        "/login", json={"email": "annabel@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid email or password"}

def test_login_with_an_unknown_email_gives_the_identical_error():
    client = make_client()
    register(client)

    known = client.post(
        "/login", json={"email": "annabel@example.com", "password": "wrong-password"}
    )
    unknown = client.post(
        "/login", json={"email": "nobody@example.com", "password": "hunter22"}
    )

    # a wrong password and an unregistered email must look the same,
    # otherwise a login attempt can be used to find out who has an account
    assert known.status_code == unknown.status_code == 401
    assert known.get_json() == unknown.get_json()

def test_logout_ends_the_session():
    client = make_client()
    register(client)
    client.post("/login", json={"email": "annabel@example.com", "password": "hunter22"})
    assert "Logged in as annabel@example.com" in client.get("/").get_data(as_text=True)

    response = client.post("/logout", json={})

    assert response.status_code == 200
    assert "Logged in as" not in client.get("/").get_data(as_text=True)
    assert 'href="/login"' in client.get("/").get_data(as_text=True)

def test_logout_when_not_logged_in_is_a_no_op():
    client = make_client()

    response = client.post("/logout", json={})

    assert response.status_code == 200

def test_login_form_logs_in_and_redirects_to_the_homepage():
    client = make_client()
    register(client)

    response = client.post(
        "/login", data={"email": "annabel@example.com", "password": "hunter22"}
    )

    assert response.status_code == 302
    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Logged in as annabel@example.com" in body

def test_login_form_with_wrong_password_shows_the_error():
    client = make_client()
    register(client)

    response = client.post(
        "/login", data={"email": "annabel@example.com", "password": "wrong-password"}
    )

    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "invalid email or password" in body

def test_logout_button_on_the_homepage_actually_logs_out():
    client = make_client()
    register(client)
    client.post("/login", json={"email": "annabel@example.com", "password": "hunter22"})

    response = client.post("/logout")
    body = client.get(response.headers["Location"]).get_data(as_text=True)

    assert "Logged in as" not in body

def login(client, email="annabel@example.com", password="hunter22"):
    return client.post("/login", json={"email": email, "password": password})

def test_a_booking_made_while_logged_in_is_linked_to_the_account():
    client = make_client()
    register(client)
    user = login(client).get_json()

    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    assert created["user_id"] == user["id"]
    assert client.get(f"/bookings/{created['id']}").get_json()["user_id"] == user["id"]

def test_a_guest_booking_has_no_user_id():
    client = make_client()

    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    assert created["user_id"] is None

def test_logging_out_before_booking_leaves_it_unlinked():
    client = make_client()
    register(client)
    login(client)
    client.post("/logout", json={})

    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    assert created["user_id"] is None

def test_a_form_booking_while_logged_in_is_linked_to_the_account():
    client = make_client()
    register(client)
    user = login(client).get_json()

    client.post("/spaces/1/book", data={"member": "annabel", **form_slot(1, 2)})

    assert client.get("/bookings/1").get_json()["user_id"] == user["id"]

def test_user_id_stays_on_the_booking_through_pay_and_list():
    client = make_client()
    register(client)
    user = login(client).get_json()

    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    paid = client.post(f"/bookings/{created['id']}/pay").get_json()

    assert paid["user_id"] == user["id"]
    assert client.get("/bookings").get_json()["bookings"][0]["user_id"] == user["id"]
    assert (
        client.get("/spaces/1/bookings").get_json()["bookings"][0]["user_id"]
        == user["id"]
    )

def test_subscribing_returns_an_active_subscription():
    client = make_client()

    response = client.post("/members/annabel/subscribe")

    assert response.status_code == 200
    body = response.get_json()
    assert body["member"] == "annabel"
    assert body["active"] is True
    assert body["started_at"]

def test_subscribing_twice_keeps_the_original_start():
    client = make_client()
    first = client.post("/members/annabel/subscribe").get_json()

    second = client.post("/members/annabel/subscribe")

    assert second.status_code == 200
    assert second.get_json() == first

def test_a_blank_member_name_cannot_subscribe():
    client = make_client()

    response = client.post("/members/%20/subscribe")

    assert response.status_code == 400
    assert response.get_json() == {"error": "member name must not be blank"}

def test_a_subscribed_members_booking_is_paid_on_creation():
    client = make_client()
    client.post("/members/annabel/subscribe")

    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)}
    ).get_json()

    assert created["paid"] is True
    # no pay step needed to get the access code
    unlock = client.post(f"/bookings/{created['id']}/unlock")
    assert unlock.status_code == 200

def test_a_member_without_a_subscription_still_pays_once():
    client = make_client()
    client.post("/members/annabel/subscribe")

    created = client.post(
        "/spaces/1/bookings", json={"member": "gregory", **slot(1, 2)}
    ).get_json()

    assert created["paid"] is False
    paid = client.post(f"/bookings/{created['id']}/pay").get_json()
    assert paid["paid"] is True

def test_subscription_matches_the_member_name_ignoring_case_and_spaces():
    client = make_client()
    client.post("/members/%20Annabel%20/subscribe")

    lower = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    shouting = client.post(
        "/spaces/1/bookings", json={"member": "  ANNABEL ", **slot(3, 4)}
    ).get_json()

    assert lower["paid"] is True
    assert shouting["paid"] is True

def test_a_subscribers_booking_adds_no_per_booking_revenue():
    client = make_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )
    client.post("/members/annabel/subscribe")

    client.post("/spaces/2/bookings", json={"member": "annabel", **slot(1, 2)})
    metrics = client.get("/metrics").get_json()

    assert metrics["paid_bookings"] == 1
    assert metrics["revenue_cents"] == 0

def test_form_booking_by_a_subscriber_is_paid():
    client = make_client()
    client.post("/members/annabel/subscribe")

    client.post("/spaces/1/book", data={"member": "annabel", **form_slot(1, 2)})

    assert client.get("/bookings/1").get_json()["paid"] is True

def test_metrics_reports_spaces_bookings_and_members():
    client = make_client()

    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6})
    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)})
    client.post("/spaces/2/bookings", json={"member": "gregory", **slot(1, 2)})

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.get_json() == {
        "spaces": 2,
        "bookings": 2,
        "paid_bookings": 0,
        "unpaid_bookings": 2,
        "members": 2,
        "revenue_cents": 0,
    }

def test_metrics_splits_paid_and_unpaid_bookings():
    client = make_client()
    first = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    client.post("/spaces/1/bookings", json={"member": "gregory", **slot(3, 4)})
    client.post("/spaces/1/bookings", json={"member": "flurina", **slot(5, 6)})
    client.post(f"/bookings/{first['id']}/pay")

    body = client.get("/metrics").get_json()

    assert body["bookings"] == 3
    assert body["paid_bookings"] == 1
    assert body["unpaid_bookings"] == 2

def test_metrics_with_no_bookings_reports_zero_for_each_count():
    client = make_client()

    body = client.get("/metrics").get_json()

    assert body["bookings"] == 0
    assert body["paid_bookings"] == 0
    assert body["unpaid_bookings"] == 0

def test_metrics_reports_revenue_from_paid_bookings():
    client = make_client()

    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )
    booking = client.post(
        "/spaces/2/bookings", json={"member": "gregory", **slot(1, 2)}
    ).get_json()

    # unpaid bookings bring in nothing yet
    assert client.get("/metrics").get_json()["revenue_cents"] == 0

    client.post(f"/bookings/{booking['id']}/pay")
    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.get_json()
    assert body["revenue_cents"] == 1500

def test_revenue_stays_the_same_when_the_space_price_changes_later():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 500},
    )
    booking = client.post(
        "/spaces/2/bookings", json={"member": "gregory", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{booking['id']}/pay")
    assert client.get("/metrics").get_json()["revenue_cents"] == 500

    # PATCH can't change a price yet, so change it straight in the database
    with app.db.cursor() as cur:
        cur.execute("UPDATE spaces SET price_cents = 2000 WHERE id = 2")

    assert client.get("/metrics").get_json()["revenue_cents"] == 500

    # a booking made after the price change is charged the new price
    later = client.post(
        "/spaces/2/bookings", json={"member": "annabel", **slot(3, 4)}
    ).get_json()
    client.post(f"/bookings/{later['id']}/pay")
    assert client.get("/metrics").get_json()["revenue_cents"] == 2500

def test_startup_fills_in_the_amount_on_bookings_made_before_the_column_existed():
    app = create_app(reset_on_start=True)
    client = app.test_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )
    with app.db.cursor() as cur:
        # a paid booking from before amount_cents existed, so it has no amount
        cur.execute(
            "INSERT INTO bookings (space_id, member, paid, start_time, end_time) "
            "VALUES (2, 'old-member', TRUE, "
            "now() + interval '1 day', now() + interval '2 days')"
        )
        cur.execute("SELECT amount_cents FROM bookings")
        assert cur.fetchone()["amount_cents"] is None

    create_app(reset_on_start=False)  # the next app start runs the backfill

    with app.db.cursor() as cur:
        cur.execute("SELECT amount_cents FROM bookings")
        assert cur.fetchone()["amount_cents"] == 1500
    assert client.get("/metrics").get_json()["revenue_cents"] == 1500

def test_health_reports_error_when_database_is_unreachable():
    app = create_app(reset_on_start=True)
    app.db.close()  # simulate a lost/broken database connection
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "error",
        "error": "database unreachable",
    }

def test_dashboard_shows_current_metrics():
    client = make_client()

    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 1500},
    )
    booking = client.post(
        "/spaces/2/bookings", json={"member": "gregory", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{booking['id']}/pay")  # revenue only counts paid

    response = client.get("/dashboard")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Spaces: 2" in body
    assert "Bookings: 1" in body
    assert "Members: 1" in body
    assert "$15.00" in body

def test_dashboard_shows_paid_and_unpaid_bookings_separately():
    client = make_client()
    first = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    second = client.post(
        "/spaces/1/bookings", json={"member": "gregory", **slot(3, 4)}
    ).get_json()
    client.post("/spaces/1/bookings", json={"member": "flurina", **slot(5, 6)})
    client.post(f"/bookings/{first['id']}/pay")
    client.post(f"/bookings/{second['id']}/pay")

    body = client.get("/dashboard").get_data(as_text=True)

    # two paid and one unpaid, so swapped labels would be caught
    assert "Bookings: 3" in body
    assert "Paid bookings: 2" in body
    assert "Unpaid bookings: 1" in body

def test_dashboard_with_no_bookings_shows_zero_paid_and_unpaid():
    client = make_client()

    body = client.get("/dashboard").get_data(as_text=True)

    assert "Paid bookings: 0" in body
    assert "Unpaid bookings: 0" in body

def test_delete_unbooked_space_removes_it():
    client = make_client()
    created = client.post(
        "/spaces", json={"name": "Temp Room", "capacity": 3}
    ).get_json()

    response = client.delete(f"/spaces/{created['id']}")

    assert response.status_code == 204
    listed = client.get("/spaces").get_json()["spaces"]
    assert all(s["id"] != created["id"] for s in listed)

def test_delete_space_with_bookings_is_rejected():
    client = make_client()
    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)})

    response = client.delete("/spaces/1")

    assert response.status_code == 409
    assert response.get_json() == {
        "error": "space has bookings, cancel them first"
    }

def test_delete_unknown_space_returns_404():
    client = make_client()

    response = client.delete("/spaces/999")

    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}

def test_get_space_returns_its_data():
    client = make_client()

    response = client.get("/spaces/1")

    assert response.status_code == 200
    assert response.get_json() == {
        "id": 1,
        "name": "Founders Desk",
        "capacity": 1,
        "price_cents": 0,
        "available": True,
    }

def test_get_unknown_space_returns_404():
    client = make_client()

    response = client.get("/spaces/999")

    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}

def test_list_spaces_for_a_time_window_reflects_bookings_in_that_window():
    client = make_client()
    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(48, 50)})

    # free right now, so the default view says available
    assert client.get("/spaces").get_json()["spaces"][0]["available"] is True

    clash = client.get("/spaces", query_string=slot(47, 49)).get_json()
    free = client.get("/spaces", query_string=slot(60, 61)).get_json()

    assert clash["spaces"][0]["available"] is False
    assert free["spaces"][0]["available"] is True

def test_availability_window_replaces_the_right_now_check():
    client = make_client()
    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)})

    assert client.get("/spaces").get_json()["spaces"][0]["available"] is False

    later = client.get("/spaces", query_string=slot(5, 6)).get_json()

    assert later["spaces"][0]["available"] is True

def test_availability_window_touching_a_booking_is_still_free():
    client = make_client()
    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(-1, 1)})
    client.post("/spaces/1/bookings", json={"member": "gregory", **slot(3, 4)})

    # starts exactly when the first booking ends
    after = client.get("/spaces", query_string=slot(1, 2)).get_json()
    # ends exactly when the second booking starts
    before = client.get("/spaces", query_string=slot(2, 3)).get_json()

    assert after["spaces"][0]["available"] is True
    assert before["spaces"][0]["available"] is True

def test_get_space_for_a_time_window_reflects_bookings_in_that_window():
    client = make_client()
    client.post("/spaces/1/bookings", json={"member": "annabel", **slot(48, 50)})

    clash = client.get("/spaces/1", query_string=slot(49, 51))
    free = client.get("/spaces/1", query_string=slot(60, 61))

    assert clash.status_code == 200
    assert clash.get_json()["available"] is False
    assert free.get_json()["available"] is True

def test_availability_window_must_have_both_times_in_order():
    client = make_client()
    together = (
        "start_time and end_time must be given together "
        "(ISO 8601 with timezone, e.g. 2026-09-25T09:00:00Z)"
    )
    bad_windows = [
        ({"start_time": slot(1, 2)["start_time"]}, together),
        ({"start_time": "tomorrow", "end_time": "later"}, together),
        (
            {"start_time": "2026-09-25T09:00:00", "end_time": "2026-09-25T10:00:00"},
            together,  # no timezone
        ),
        (slot(2, 1), "end_time must be after start_time"),
    ]

    for path in ["/spaces", "/spaces/1"]:
        for query, message in bad_windows:
            response = client.get(path, query_string=query)

            assert response.status_code == 400
            assert response.get_json() == {"error": message}

def test_list_bookings_for_a_space_returns_all_of_them():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6})
    later = client.post(
        "/spaces/1/bookings", json={"member": "gregory", **slot(3, 4)}
    ).get_json()
    earlier = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()
    client.post("/spaces/2/bookings", json={"member": "flurina", **slot(1, 2)})

    response = client.get("/spaces/1/bookings")

    # only space 1's bookings, earliest first
    assert response.status_code == 200
    assert response.get_json() == {"bookings": [earlier, later]}

def test_list_bookings_for_space_without_bookings_is_empty():
    client = make_client()

    response = client.get("/spaces/1/bookings")

    assert response.status_code == 200
    assert response.get_json() == {"bookings": []}

def test_list_bookings_for_unknown_space_returns_404():
    client = make_client()

    response = client.get("/spaces/999/bookings")

    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}

def test_booking_more_people_than_capacity_is_rejected():
    client = make_client()

    # Founders Desk (space 1) has capacity 1
    response = client.post(
        "/spaces/1/bookings",
        json={"member": "annabel", "party_size": 2, **slot(1, 2)},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "party_size 2 exceeds this space's capacity of 1"
    }
    assert client.get("/spaces/1/bookings").get_json() == {"bookings": []}

def test_booking_up_to_capacity_is_allowed():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6})

    response = client.post(
        "/spaces/2/bookings",
        json={"member": "annabel", "party_size": 6, **slot(1, 2)},
    )

    assert response.status_code == 201

def test_booking_with_invalid_party_size_is_rejected():
    client = make_client()

    for party_size in [0, -3, "two", 1.5, True]:
        response = client.post(
            "/spaces/1/bookings",
            json={"member": "annabel", "party_size": party_size, **slot(1, 2)},
        )

        assert response.status_code == 400
        assert response.get_json() == {
            "error": "party_size must be a whole number of at least 1"
        }
def test_list_bookings_returns_bookings_across_all_spaces():
    client = make_client()
    client.post("/spaces", json={"name": "Meeting Room A", "capacity": 6})
    later = client.post(
        "/spaces/1/bookings", json={"member": "gregory", **slot(3, 4)}
    ).get_json()
    earlier = client.post(
        "/spaces/2/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    response = client.get("/bookings")

    # bookings from both spaces, earliest first
    assert response.status_code == 200
    assert response.get_json() == {"bookings": [earlier, later]}

def test_list_bookings_when_there_are_none_is_empty():
    client = make_client()

    response = client.get("/bookings")

    assert response.status_code == 200
    assert response.get_json() == {"bookings": []}

def test_update_space_name_shows_up_in_list():
    client = make_client()

    response = client.patch("/spaces/1", json={"name": "Founders Desk (Window)"})

    assert response.status_code == 200
    assert response.get_json() == {
        "id": 1,
        "name": "Founders Desk (Window)",
        "capacity": 1,
        "price_cents": 0,
    }
    spaces = client.get("/spaces").get_json()["spaces"]
    assert spaces[0]["name"] == "Founders Desk (Window)"
    assert spaces[0]["capacity"] == 1  # untouched

def test_update_space_capacity_only_keeps_the_name():
    client = make_client()

    response = client.patch("/spaces/1", json={"capacity": 4})

    assert response.status_code == 200
    assert response.get_json()["name"] == "Founders Desk"
    assert response.get_json()["capacity"] == 4

def test_update_space_keeps_its_bookings():
    client = make_client()
    booking = client.post(
        "/spaces/1/bookings", json={"member": "annabel", **slot(1, 2)}
    ).get_json()

    client.patch("/spaces/1", json={"name": "Renamed Desk"})

    assert client.get("/spaces/1/bookings").get_json() == {"bookings": [booking]}

def test_update_space_price_shows_up_in_list():
    client = make_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 500},
    )

    response = client.patch("/spaces/2", json={"price_cents": 2000})

    assert response.status_code == 200
    assert response.get_json() == {
        "id": 2,
        "name": "Meeting Room A",
        "capacity": 6,
        "price_cents": 2000,
    }
    listed = client.get("/spaces").get_json()["spaces"]
    assert next(s for s in listed if s["id"] == 2)["price_cents"] == 2000

    # 0 is a valid price: the space becomes free
    free = client.patch("/spaces/2", json={"price_cents": 0})
    assert free.get_json()["price_cents"] == 0

def test_update_space_name_only_keeps_the_price():
    client = make_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 500},
    )

    response = client.patch("/spaces/2", json={"name": "Meeting Room B"})

    assert response.get_json()["price_cents"] == 500

def test_changing_a_price_with_patch_only_affects_later_bookings():
    client = make_client()
    client.post(
        "/spaces",
        json={"name": "Meeting Room A", "capacity": 6, "price_cents": 500},
    )
    before = client.post(
        "/spaces/2/bookings", json={"member": "gregory", **slot(1, 2)}
    ).get_json()
    client.post(f"/bookings/{before['id']}/pay")
    assert client.get("/metrics").get_json()["revenue_cents"] == 500

    client.patch("/spaces/2", json={"price_cents": 2000})

    # the booking made before the change keeps what it was charged
    assert client.get("/metrics").get_json()["revenue_cents"] == 500

    after = client.post(
        "/spaces/2/bookings", json={"member": "annabel", **slot(3, 4)}
    ).get_json()
    client.post(f"/bookings/{after['id']}/pay")
    assert client.get("/metrics").get_json()["revenue_cents"] == 2500

def test_update_unknown_space_returns_404():
    client = make_client()

    response = client.patch("/spaces/999", json={"name": "Ghost Room"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}

def test_update_space_with_invalid_values_is_rejected():
    client = make_client()

    price_error = "price_cents must be a non-negative integer"
    cases = [
        ({}, "provide name, capacity and/or price_cents to update"),
        ({"name": "   "}, "name must not be empty"),
        ({"name": None}, "name must not be empty"),
        ({"capacity": 0}, "capacity must be a whole number of at least 1"),
        ({"capacity": "4"}, "capacity must be a whole number of at least 1"),
        ({"price_cents": -1}, price_error),
        ({"price_cents": "5"}, price_error),
        ({"price_cents": 2.5}, price_error),
        ({"price_cents": None}, price_error),
        ({"price_cents": True}, price_error),
    ]
    for body, error in cases:
        response = client.patch("/spaces/1", json=body)

        assert response.status_code == 400
        assert response.get_json() == {"error": error}

    # nothing changed
    space = client.get("/spaces/1").get_json()
    assert space["name"] == "Founders Desk"
    assert space["price_cents"] == 0


def test_homepage_links_to_dashboard():
    client = make_client()

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'href="/dashboard"' in body

def test_dashboard_links_back_to_homepage():
    client = make_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'href="/"' in body