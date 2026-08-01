from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_vite_dev_origin() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/qualities",
        headers={"origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
