from fastapi.testclient import TestClient
from solution_copilot.infrastructure import health

from apps.api.main import app

client = TestClient(app)


def test_liveness_does_not_require_infrastructure(monkeypatch):
    monkeypatch.setattr(health, "get_settings", lambda: (_ for _ in ()).throw(ValueError()))
    assert client.get("/api/v1/health/live").status_code == 200


def test_readiness_reports_failure_without_leaking_secrets(monkeypatch):
    def fail():
        raise RuntimeError("postgresql://user:secret@host/private")

    monkeypatch.setattr(health, "check_postgres", fail)
    monkeypatch.setattr(health, "check_redis", lambda: None)
    monkeypatch.setattr(health, "check_storage", lambda: None)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["services"] == {
        "postgres": "unavailable",
        "redis": "ok",
        "storage": "ok",
    }
    assert "secret" not in response.text


def test_readiness_success(monkeypatch):
    for name in ["check_postgres", "check_redis", "check_storage"]:
        monkeypatch.setattr(health, name, lambda: None)
    assert client.get("/api/v1/health/ready").json()["status"] == "ok"
