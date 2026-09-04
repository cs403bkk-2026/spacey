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
