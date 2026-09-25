from src.app import create_app


def test_health() -> None:
    client = create_app().test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
