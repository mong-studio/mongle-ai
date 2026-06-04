def test_health_ok(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_available(api_client):
    assert api_client.get("/openapi.json").status_code == 200
