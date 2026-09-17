from app import create_app

def make_client():
    return create_app(reset_on_start=True).test_client()

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
            {"id": 1, "name": "Founders Desk", "capacity": 1, "available": True}
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
    }

    listed = client.get("/spaces").get_json()["spaces"]
    assert {
        "id": 2,
        "name": "Meeting Room A",
        "capacity": 6,
        "available": True,
    } in listed

def test_create_space_without_capacity_is_rejected():
    client = make_client()

    response = client.post("/spaces", json={"name": "No Capacity Room"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "name and capacity are required"}

def test_create_booking_for_existing_space_succeeds():
    client = make_client()

    response = client.post(
        "/spaces/1/bookings", json={"member": "annabel"}
    )

    assert response.status_code == 201
    assert response.get_json() == {
        "id": 1,
        "space_id": 1,
        "member": "annabel",
        "paid": True,
    }

def test_create_booking_for_unknown_space_returns_404():
    client = make_client()

    response = client.post("/spaces/999/bookings", json={"member": "annabel"})

    #404 to reject booking a space that doesn't exist
    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}

def test_booking_an_already_booked_space_is_rejected():
    client = make_client()

    client.post("/spaces/1/bookings", json={"member": "annabel"})
    response = client.post("/spaces/1/bookings", json={"member": "gregory"})

    assert response.status_code == 409
    assert response.get_json() == {"error": "space is already booked"}

def test_booked_space_shows_as_unavailable():
    client = make_client()

    client.post("/spaces/1/bookings", json={"member": "annabel"})
    response = client.get("/spaces")

    spaces = response.get_json()["spaces"]
    founders_desk = next(s for s in spaces if s["id"] == 1)
    assert founders_desk["available"] is False

def test_find_booking_returns_the_booking():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel"}
    ).get_json()

    response = client.get(f"/bookings/{created['id']}")

    assert response.status_code == 200
    assert response.get_json() == {
        "id": 1,
        "space_id": 1,
        "member": "annabel",
        "paid": True,
    }

def test_find_unknown_booking_returns_404():
    client = make_client()

    response = client.get("/bookings/999")

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}

def test_cancel_booking_makes_space_available_again():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel"}
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

def test_unlock_a_paid_booking_returns_an_access_code():
    client = make_client()
    created = client.post(
        "/spaces/1/bookings", json={"member": "annabel"}
    ).get_json()

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
    client.post("/spaces/1/bookings", json={"member": "annabel"})
    client.post("/spaces/2/bookings", json={"member": "gregory"})

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.get_json() == {
        "spaces": 2,
        "bookings": 2,
        "members": 2, 
    } 

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
    client.post("/spaces/1/bookings", json={"member": "annabel"})

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
