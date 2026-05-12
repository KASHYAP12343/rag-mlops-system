from tests.conftest import client


def test_health_endpoint():
    """
    Verify liveness endpoint works.
    """

    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "healthy"
    assert data["service"] == "rag-api"


def test_ready_endpoint():
    """
    Verify readiness endpoint responds correctly.
    """

    response = client.get("/ready")

    # ready OR not_ready acceptable during local testing
    assert response.status_code in [200, 503]

    data = response.json()

    assert "status" in data
    assert "dependencies" in data