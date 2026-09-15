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