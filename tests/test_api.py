"""API integration tests."""
import pytest
from fastapi.testclient import TestClient

# We import after ensuring config paths exist
import sys
sys.path.insert(0, ".")

from api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "tools_loaded" in data


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "python_info" in response.text or "request" in response.text


def test_api_key_rejection():
    # When API_KEY is set, unauthorized requests should fail
    import config
    if not config.API_KEY:
        pytest.skip("API_KEY not configured")
    response = client.post("/api/chat", json={"message": "hi"})
    assert response.status_code in (401, 403)
