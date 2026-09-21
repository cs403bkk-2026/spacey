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

def test_update_unknown_space_returns_404():
    client = make_client()

    response = client.patch("/spaces/999", json={"name": "Ghost Room"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}

def test_update_space_with_invalid_values_is_rejected():
    client = make_client()

    cases = [
        ({}, "provide name and/or capacity to update"),
        ({"name": "   "}, "name must not be empty"),
        ({"name": None}, "name must not be empty"),
        ({"capacity": 0}, "capacity must be a whole number of at least 1"),
        ({"capacity": "4"}, "capacity must be a whole number of at least 1"),
    ]
    for body, error in cases:
        response = client.patch("/spaces/1", json=body)

        assert response.status_code == 400
        assert response.get_json() == {"error": error}

    # nothing changed
    assert client.get("/spaces/1").get_json()["name"] == "Founders Desk"


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