def test_health_ok(api_client):
    """/health는 200과 {"status": "ok"}를 반환한다."""
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_available(api_client):
    """/openapi.json 문서 엔드포인트가 200으로 응답한다."""
    assert api_client.get("/openapi.json").status_code == 200
