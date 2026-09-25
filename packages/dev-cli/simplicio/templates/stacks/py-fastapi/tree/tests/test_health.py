"""Smoke test that the scaffold compiles + runs before any planner task lands."""
from fastapi.testclient import TestClient

from main import app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
