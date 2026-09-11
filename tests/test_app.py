from app import create_app


def test_health_reports_running_revision(monkeypatch):
    monkeypatch.setenv("APP_REVISION", "test-revision")
    client = create_app().test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "revision": "test-revision",
        "status": "ok",
    }

def test_list_spaces_returns_the_seed_space():
    client = create_app().test_client()

    response = client.get("/spaces")

    assert response.status_code == 200
    assert response.get_json() == {
        "spaces": [{"id": 1, "name": "Founders Desk", "capacity": 1}]
    }

def test_create_booking_for_existing_space_succeeds():
    client = create_app().test_client()

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
    client = create_app().test_client()

    response = client.post("/spaces/999/bookings", json={"member": "annabel"})

    #404 to reject booking a space that doesn't exist
    assert response.status_code == 404
    assert response.get_json() == {"error": "space not found"}