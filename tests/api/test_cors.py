def test_cors_preflight_allows_web_origin(api_client):
    resp = api_client.options(
        "/v1/todo/chat",
        headers={
            "Origin": "https://mongle-village.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key,content-type",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://mongle-village.com"
